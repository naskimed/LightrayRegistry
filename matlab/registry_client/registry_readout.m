function registry_readout(job_json)
%REGISTRY_READOUT  The certification READOUT for ONE pinned config, on any population.
%
%   Reproduces the tierB_readout.m + tierB_gate_completion.m (clause 5) measurement for
%   the S1_soft arm (validated against the manual certified SELL to 4 significant
%   figures: pooled 1.6455 / uplift +0.2068 / reseeds 1.604,1.604,1.634 / carrier J .984):
%     1. mask train           (tierB_mask, constants from the JOB — see below)
%     2. fit the pinned config on masked-train   (fit_soft_cfg — THE shared estimator,
%        param-hash seed: identical to what the search objective evaluated)
%     3. select blobs on TRAIN only               (train PF >= sel_pf AND n >= sel_min_tr)
%     4. kNN-bridge ALL trades to train blobs     (k = knn_k, mode of neighbours)
%     5. per-window + pooled W2:W4 PF of the selection vs S0, under the param-hash seed
%        AND reseeds {1,2,3}; masked-train geometry z; carrier Jaccard.
%
%   SINGLE-SOURCED CONSTANTS: everything comes from the job contract (windows, embargo,
%   fit, select, null) and is echoed back in the result as pc_echo — this file no longer
%   calls precommit() off whatever BelkaSGL tree is on the path (the drift class where
%   search and readout could silently disagree on windows).
%
%   job.json: belkasgl_path, side, tag, result_path, config{K,kernel,sigma,k_nbrs,gamma,
%   n_diff,w_*}, windows/embargo/exclusions/min_window_side, fit{kmeans_reps,
%   n_floor{floor,frac}, indeg_q}, select{sel_pf, sel_min_tr, knn_k}, null{n_shuffles,
%   shuffle_seed, pf_floor, pf_cap, min_trades}, AND either population_parquet (registry)
%   OR legacy_txt+legacy_csv.
    job = jsondecode(fileread(job_json));
    addpath(job.belkasgl_path);
    if isfolder(fullfile(job.belkasgl_path, 'ICDE')), addpath(fullfile(job.belkasgl_path, 'ICDE')); end
    side = job.side;

    % ---- population: registry parquet (fresh) OR the legacy EA pair -----------------------
    if isfield(job, 'population_parquet')
        [raw, profits, dates] = read_population(job.population_parquet, side);
    else
        [buy_data, sell_data] = read_belka_config(job.legacy_txt);
        [buy_prof, sell_prof, buy_dates, sell_dates] = read_trades(job.legacy_csv);
        if strcmp(side, 'buy'), sdat = buy_data; sprf = buy_prof; sdte = buy_dates;
        else,                   sdat = sell_data; sprf = sell_prof; sdte = sell_dates; end
        n_use = min(size(sdat, 1), length(sprf));
        raw = sdat(1:n_use, 2:7); profits = sprf(1:n_use); dates = sdte(1:n_use);
    end
    N = numel(profits);

    % ---- mask (job-sourced constants) + train-only standardisation ------------------------
    M  = tierB_mask(dates, mask_pc_from_job(job));
    tr = M.is_train;
    [Xtr, pp]  = preprocess_fit(raw(tr, :));
    Xall       = zeros(N, size(Xtr, 2));
    Xall(tr,:) = Xtr;  Xall(~tr,:) = preprocess_apply(raw(~tr, :), pp);
    prof_tr    = profits(tr);
    nW         = numel(job.windows.names);
    C  = struct('kmeans_reps', job.fit.kmeans_reps, ...
                'n_floor', max(job.fit.n_floor.floor, ceil(job.fit.n_floor.frac * sum(tr))), ...
                'indeg_q', job.fit.indeg_q);
    sel_cfg = job.select;
    nu = job.null;

    % ---- the pinned config -----------------------------------------------------------------
    c = job.config;
    p = struct('kernel', c.kernel, 'sigma', c.sigma, 'k_nbrs', c.k_nbrs, 'gamma', c.gamma, ...
               'n_diff', c.n_diff, 'w_hour', c.w_hour, 'w_ema', c.w_ema, 'w_mom', c.w_mom, ...
               'w_dv', c.w_dv, 'w_iv', c.w_iv, 'w_hurst', c.w_hurst);
    K = c.K;
    w = [p.w_hour, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst];

    s0 = pf_num(profits(M.win_id >= 2));                 % S0 unconditional pooled W2:W4

    % ---- certified fit (param-hash seed, THE shared estimator) → select → bridge ----------
    % No try/catch: a failed certified fit must error loudly with its real diagnostics
    % (the old assert-after-swallowing-fit_seed produced 'certified refit failed' and nothing).
    cert_seed = sgl_param_seed(p, K);
    bid_cert  = fit_soft_cfg(p, K, Xtr, C, cert_seed);
    sel = sel_rule(bid_cert, prof_tr, sel_cfg);
    Xw  = Xall .* w;
    idx = knnsearch(Xw(tr, :), Xw, 'K', min(sel_cfg.knn_k, sum(tr)));
    br  = mode(bid_cert(idx), 2);
    traded = M.win_id > 0 & ismember(br, sel);
    perW = nan(1, nW);
    for wi = 1:nW, perW(wi) = pf_num(profits(traded & M.win_id == wi)); end
    n_perW   = arrayfun(@(wi) sum(traded & M.win_id == wi), 1:nW);
    pooled   = pf_num(profits(M.win_id >= 2 & ismember(br, sel)));
    n_pooled = sum(M.win_id >= 2 & ismember(br, sel));

    % certified carrier = selected blob with max pooled W2:W4 count
    best_k = NaN; best_n = -1;
    for k = sel(:)'
        nk = sum(br == k & M.win_id >= 2);
        if nk > best_n, best_n = nk; best_k = k; end
    end
    memb_cert        = find(bid_cert == best_k);
    carrier_train_pf = pf_num(prof_tr(bid_cert == best_k));
    carrier_train_n  = sum(bid_cert == best_k);
    carrier_W4_pf    = pf_num(profits(br == best_k & M.win_id == nW));
    carrier_W4_n     = sum(br == best_k & M.win_id == nW);

    % ---- masked-train geometry z (same CRN construction as the search) ---------------------
    rs     = RandStream('mt19937ar', 'Seed', nu.shuffle_seed);
    shifts = randi(rs, sum(tr) - 1, nu.n_shuffles, 1);
    Rz     = sep_z(bid_cert, prof_tr, shifts, nu.min_trades, nu.pf_floor, nu.pf_cap);

    % ---- reseeds {1,2,3} (gate clause 5) ---------------------------------------------------
    reseeds = struct('seed', {}, 'pooled', {}, 'jaccard', {}, 'selected', {});
    for sd = [1 2 3]
        try
            bid_s = fit_soft_cfg(p, K, Xtr, C, sd);
        catch err
            fprintf('  reseed %d FAILED: %s\n', sd, err.message);
            reseeds(end+1) = struct('seed', sd, 'pooled', NaN, 'jaccard', NaN, 'selected', false);
            continue;
        end
        sel_s  = sel_rule(bid_s, prof_tr, sel_cfg);
        br_s   = mode(bid_s(idx), 2);
        pool_s = pf_num(profits(M.win_id >= 2 & ismember(br_s, sel_s)));
        bestJ = 0; bestB = NaN;
        for k = unique(bid_s(bid_s > 0))'
            m = find(bid_s == k);
            J = numel(intersect(m, memb_cert)) / numel(union(m, memb_cert));
            if J > bestJ, bestJ = J; bestB = k; end
        end
        reseeds(end+1) = struct('seed', sd, 'pooled', pool_s, 'jaccard', bestJ, ...
                                'selected', any(sel_s == bestB));
    end

    out = struct('tag', job.tag, 'side', side, 'N', N, 'n_train', sum(tr), ...
        'win_counts', M.counts(:)', 'masked_z', Rz.z, 'cert_seed', cert_seed, ...
        'n_blobs', numel(unique(bid_cert(bid_cert>0))), 'n_selected', numel(sel), ...
        'S0_W2W4', s0, 'per_window_pf', perW, 'per_window_n', n_perW, ...
        'pooled_W2W4', pooled, 'n_pooled', n_pooled, 'uplift', pooled - s0, ...
        'carrier_blob', best_k, 'carrier_train_n', carrier_train_n, ...
        'carrier_train_pf', carrier_train_pf, 'carrier_W4_n', carrier_W4_n, ...
        'carrier_W4_pf', carrier_W4_pf, 'reseeds', reseeds);
    out.pc_echo = struct('windows', job.windows, 'embargo', job.embargo, ...
        'min_window_side', job.min_window_side, 'fit', job.fit, 'select', sel_cfg, 'null', nu);
    out.engine_stamp = struct('name', 'matlab_sgl', 'version', version, 'git', 'server');
    fid = fopen(job.result_path, 'w'); fprintf(fid, '%s', jsonencode(out)); fclose(fid);
    fprintf('READOUT %s (%s): masked_z=%.2f | S0=%.2f pooled=%.2f uplift=%+.2f | reseeds %s | carrierJ %s\n', ...
        job.tag, side, Rz.z, s0, pooled, pooled - s0, mat2str([reseeds.pooled], 3), ...
        mat2str([reseeds.jaccard], 2));
end


%% ── locals (verbatim from tierB_readout.m / tierB_gate_completion.m) ─────────────────────
function v = pf_num(p)
    if isempty(p), v = NaN; return; end
    gw = sum(p(p > 0)); gl = abs(sum(p(p <= 0)));
    if gl > 0, v = gw / gl; elseif gw > 0, v = 10; else, v = NaN; end
end

function sel = sel_rule(bid, prof, sc)
    sel = [];
    for k = unique(bid(bid > 0))'
        p = prof(bid == k);
        gw = sum(p(p > 0)); gl = abs(sum(p(p <= 0)));
        pf = 0; if gl > 0, pf = gw / gl; elseif gw > 0, pf = 10; end
        if pf >= sc.sel_pf && numel(p) >= sc.sel_min_tr, sel(end+1) = k; end %#ok<AGROW>
    end
end
