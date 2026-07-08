function registry_readout(job_json)
%REGISTRY_READOUT  The certification READOUT for ONE pinned config, on any population.
%
%   Reproduces the tierB_readout.m + tierB_gate_completion.m (clause 5) measurement for the
%   S1_soft arm, so a fresh-data reproduction is comparable to the manual certified number:
%     1. mask train  (tierB_mask — the SAME windows/embargo, unchanged)
%     2. fit the pinned config on masked-train  (fit_soft pipeline, validated primitives)
%     3. select blobs on TRAIN only  (train PF >= PC.sel_pf AND n >= PC.sel_min_tr)
%     4. kNN-bridge ALL trades to train blobs  (k = PC.knn_k, mode of neighbours)
%     5. report per-window + pooled W2:W4 PF of the selection vs S0, under the param-hash
%        seed AND reseeds {1,2,3}; plus masked-train geometry z and carrier Jaccard.
%   Calls YOUR functions unchanged (precommit, tierB_mask, preprocess_fit/apply, psd_kernels,
%   sgl_graph, robust_eigs, extract_blobs_dust, sep_z, knnsearch). MATLAB never hashes.
%
%   job.json: belkasgl_path, side, tag, result_path, config{K,kernel,sigma,k_nbrs,gamma,
%   n_diff,w_hour..w_hurst}, AND either population_parquet (registry) OR legacy_txt+legacy_csv.
    job = jsondecode(fileread(job_json));
    addpath(job.belkasgl_path);
    if isfolder(fullfile(job.belkasgl_path, 'ICDE')), addpath(fullfile(job.belkasgl_path, 'ICDE')); end
    PC   = precommit();                                  % windows, embargo, sel_pf, knn_k, seeds...
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

    % ---- mask (the SAME tierB_mask) + train-only standardisation --------------------------
    M  = tierB_mask(dates, PC);
    tr = M.is_train;
    [Xtr, pp]  = preprocess_fit(raw(tr, :));
    Xall       = zeros(N, size(Xtr, 2));
    Xall(tr,:) = Xtr;  Xall(~tr,:) = preprocess_apply(raw(~tr, :), pp);
    prof_tr    = profits(tr);
    n_floor    = PC.n_floor_fun(sum(tr));
    nW         = size(PC.windows, 1);

    % ---- the pinned config ----------------------------------------------------------------
    c = job.config;
    p = struct('kernel', c.kernel, 'sigma', c.sigma, 'k_nbrs', c.k_nbrs, 'gamma', c.gamma, ...
               'n_diff', c.n_diff, 'w_hour', c.w_hour, 'w_ema', c.w_ema, 'w_mom', c.w_mom, ...
               'w_dv', c.w_dv, 'w_iv', c.w_iv, 'w_hurst', c.w_hurst);
    K = c.K;
    w = [p.w_hour, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst];

    s0 = pf_num(profits(M.win_id >= 2));                 % S0 unconditional pooled W2:W4

    % ---- certified fit (param-hash seed) → select → bridge --------------------------------
    [bid_cert, okC] = fit_seed(p, K, Xtr, PC, n_floor, hash_key(p, K));
    assert(okC, 'certified fit failed');
    sel = sel_rule(bid_cert, prof_tr, PC);
    Xw  = Xall .* w;
    idx = knnsearch(Xw(tr, :), Xw, 'K', min(PC.knn_k, sum(tr)));
    br  = mode(bid_cert(idx), 2);
    traded = M.win_id > 0 & ismember(br, sel);
    perW = nan(1, nW);
    for wi = 1:nW, perW(wi) = pf_num(profits(traded & M.win_id == wi)); end
    n_perW = arrayfun(@(wi) sum(traded & M.win_id == wi), 1:nW);
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

    % ---- masked-train geometry z (IS separation vs CRN null) ------------------------------
    rs     = RandStream('mt19937ar', 'Seed', PC.shuffle_seed);
    shifts = randi(rs, sum(tr) - 1, PC.n_shuffles, 1);
    Rz     = sep_z(bid_cert, prof_tr, shifts, PC.min_trades, PC.pf_floor, PC.pf_cap);

    % ---- reseeds {1,2,3} (gate clause 5) --------------------------------------------------
    reseeds = struct('seed', {}, 'pooled', {}, 'jaccard', {}, 'selected', {});
    for sd = [1 2 3]
        [bid_s, okS] = fit_seed(p, K, Xtr, PC, n_floor, sd);
        if ~okS, reseeds(end+1) = struct('seed', sd, 'pooled', NaN, 'jaccard', NaN, 'selected', false); continue; end
        sel_s  = sel_rule(bid_s, prof_tr, PC);
        br_s   = mode(bid_s(idx), 2);
        pool_s = pf_num(profits(M.win_id >= 2 & ismember(br_s, sel_s)));
        bestJ = 0; bestB = NaN;
        for k = unique(bid_s(bid_s > 0))'
            m = find(bid_s == k);
            J = numel(intersect(m, memb_cert)) / numel(union(m, memb_cert));
            if J > bestJ, bestJ = J; bestB = k; end
        end
        reseeds(end+1) = struct('seed', sd, 'pooled', pool_s, 'jaccard', bestJ, 'selected', any(sel_s == bestB));
    end

    out = struct('tag', job.tag, 'side', side, 'N', N, 'n_train', sum(tr), ...
        'win_counts', M.counts(:)', 'masked_z', Rz.z, 'n_blobs', numel(unique(bid_cert(bid_cert>0))), ...
        'n_selected', numel(sel), 'S0_W2W4', s0, 'per_window_pf', perW, 'per_window_n', n_perW, ...
        'pooled_W2W4', pooled, 'n_pooled', n_pooled, 'uplift', pooled - s0, ...
        'carrier_blob', best_k, 'carrier_train_n', carrier_train_n, 'carrier_train_pf', carrier_train_pf, ...
        'carrier_W4_n', carrier_W4_n, 'carrier_W4_pf', carrier_W4_pf, 'reseeds', reseeds);
    fid = fopen(job.result_path, 'w'); fprintf(fid, '%s', jsonencode(out)); fclose(fid);
    fprintf('READOUT %s (%s): masked_z=%.2f | S0=%.2f pooled=%.2f uplift=%+.2f | reseeds %s | carrierJ %s\n', ...
        job.tag, side, Rz.z, s0, pooled, pooled - s0, mat2str([reseeds.pooled], 3), mat2str([reseeds.jaccard], 2));
end


%% ── locals (verbatim from tierB_gate_completion.m / tierB_readout.m) ─────────────────────
function v = pf_num(p)
    if isempty(p), v = NaN; return; end
    gw = sum(p(p > 0)); gl = abs(sum(p(p <= 0)));
    if gl > 0, v = gw / gl; elseif gw > 0, v = 10; else, v = NaN; end
end

function sel = sel_rule(bid, prof, PC)
    sel = [];
    for k = unique(bid(bid > 0))'
        p = prof(bid == k);
        gw = sum(p(p > 0)); gl = abs(sum(p(p <= 0)));
        pf = 0; if gl > 0, pf = gw / gl; elseif gw > 0, pf = 10; end
        if pf >= PC.sel_pf && numel(p) >= PC.sel_min_tr, sel(end+1) = k; end %#ok<AGROW>
    end
end

function sd = hash_key(p, K)
    key = sprintf('s|%s|%.4f|%d|%.4f|%d|%d|%.3f%.3f%.3f%.3f%.3f%.3f', p.kernel, p.sigma, ...
        p.k_nbrs, p.gamma, p.n_diff, K, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst);
    sd = 5381; for c = double(key), sd = mod(sd*33 + c, 2^31 - 1); end
end

function [bid, ok] = fit_seed(p, K, X, PC, n_floor, seed)
    bid = []; ok = false;
    try
        w = [p.w_hour, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst];
        Xw = X .* w; N = size(Xw, 1);
        rs = RandStream('mt19937ar', 'Seed', seed);
        prev = RandStream.setGlobalStream(rs);
        clean = onCleanup(@() RandStream.setGlobalStream(prev)); %#ok<NASGU>
        Kk = psd_kernels(Xw, p.kernel, p.sigma);
        [W, Sa] = sgl_graph(Xw, Kk, min(p.k_nbrs, N - 1), p.gamma);  W = max(W, 0);
        d = max(full(sum(W, 2)), 1e-12);
        Di = spdiags(1./sqrt(d), 0, N, N);  Ks2 = (Di*W*Di); Ks2 = (Ks2 + Ks2')/2;
        [V, lam] = robust_eigs(Ks2, K + 1, 'LM');
        [lam, ix] = sort(lam, 'descend'); V = V(:, ix); lam = max(lam, 0);
        Vd = V(:, 2:end) .* (lam(2:end) .^ p.n_diff)';
        rn = max(sqrt(sum(Vd.^2, 2)), 1e-12);
        lab = kmeans(Vd./rn, K, 'Replicates', PC.kmeans_reps, 'MaxIter', 300, ...
                     'EmptyAction', 'singleton', 'Display', 'off');
        bid = extract_blobs_dust(lab, Sa, n_floor, PC.indeg_q);  ok = true;
    catch
    end
end
