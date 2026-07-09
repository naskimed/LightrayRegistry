function registry_sgl_search(job_json)
%REGISTRY_SGL_SEARCH  The SGL geometry+weight SEARCH (bayesopt, 11 vars per K) —
%   corrected-estimator version.
%
%   ESTIMATOR IDENTITY: the objective, the per-K final evaluation, and the
%   certification readout all evaluate fit_soft_cfg with the param-hash seed —
%   one function, one seed rule. The objective is therefore a DETERMINISTIC
%   function of the parameters (IsObjectiveDeterministic is now TRUE, truthfully),
%   and the searched z is the same quantity the readout will refit. This replaces
%   the prior sgl_geom (Replicates=1, ambient global RNG stream, raw eigs, no dust
%   extraction, full-sample preprocessing) whose reported values were functions of
%   (params, stream position) — irreproducible from params alone.
%
%   MASK BEFORE PREPROCESS: tierB_mask first, then preprocess_fit on masked-train
%   rows ONLY (train-only standardization stats, matching the readout; the prior
%   order leaked window rows into the winsorize/median/IQR stats).
%
%   SELECTOR IS PINNED IN THE JOB: job.selector ('z'|'sep') — the engine applies
%   it and emits out.selected. No out.best to re-rank by hand (the campaign's
%   K=8-by-sep vs K=2-by-z column-picking).
%
%   job.json: belkasgl_path, population_parquet, side, K_values[], windows{names,
%   starts,ends}, embargo{left_d,right_d}, exclusions{starts,ends}, min_window_side,
%   fit{kmeans_reps, n_floor{floor,frac}, indeg_q}, search{11 bounds}, budget
%   {n_trials,n_seed,runs_per_k}, null{n_shuffles,shuffle_seed,pf_floor,pf_cap,
%   min_trades}, selector, rng_seed, result_path, progress_path?, job_hash.
    job = jsondecode(fileread(job_json));
    addpath(job.belkasgl_path);
    if isfolder(fullfile(job.belkasgl_path, 'ICDE')), addpath(fullfile(job.belkasgl_path, 'ICDE')); end
    assert(isfield(job, 'windows'), 'windows block REQUIRED — unmasked search is not a job kind');
    assert(isfield(job, 'selector') && any(strcmp(job.selector, {'z','sep'})), ...
        'job.selector (''z''|''sep'') REQUIRED — the selector is pinned in the contract');
    assert(isfield(job, 'objective') && any(strcmp(job.objective, {'z','sep'})), ...
        ['job.objective (''z''|''sep'') REQUIRED — pinned in the contract. ''z'' = the manual ' ...
         'tierB objective (tb_z_soft: fit -> sep_z -> R.z, CRN shifts shared across evals); ' ...
         '''sep'' = the IS separation score (main_sgl_is). The objective changes WHICH peak ' ...
         'the search finds — it is part of the frozen design, never a runtime choice.']);

    if isfield(job, 'population_parquet')
        [features_raw, profits, dates] = read_population(job.population_parquet, job.side);
    else                                              % legacy EA pair (same branch as the readout)
        [buy_data, sell_data] = read_belka_config(job.legacy_txt);
        [buy_prof, sell_prof, buy_dates, sell_dates] = read_trades(job.legacy_csv);
        if strcmp(job.side, 'buy'), sdat = buy_data; sprf = buy_prof; sdte = buy_dates;
        else,                       sdat = sell_data; sprf = sell_prof; sdte = sell_dates; end
        n_use = min(size(sdat, 1), length(sprf));
        features_raw = sdat(1:n_use, 2:7); profits = sprf(1:n_use); dates = sdte(1:n_use);
    end

    % ── mask FIRST, then train-only preprocessing (readout-identical order) ────────────
    M = tierB_mask(dates, mask_pc_from_job(job));        % BLOCKS if any window < min side
    [Xtr, ~] = preprocess_fit(features_raw(M.is_train, :));
    profits  = profits(M.is_train);
    N = size(Xtr, 1);
    fprintf('  masked-train: %d of %d trades | window counts %s\n', N, numel(M.is_train), ...
        mat2str(M.counts(:)'));

    C = struct('kmeans_reps', job.fit.kmeans_reps, ...
               'n_floor', max(job.fit.n_floor.floor, ceil(job.fit.n_floor.frac * N)), ...
               'indeg_q', job.fit.indeg_q);
    nu = job.null;
    rs_sh  = RandStream('mt19937ar', 'Seed', nu.shuffle_seed);
    shifts = randi(rs_sh, N - 1, nu.n_shuffles, 1);      % CRN: one shift vector, all configs

    s = job.search;
    vars = [ optimizableVariable('kernel', {'rbf','matern','rational'}, 'Type','categorical')
             optimizableVariable('sigma',  s.sigma(:)')
             optimizableVariable('k_nbrs', s.k_nbrs(:)', 'Type','integer')
             optimizableVariable('gamma',  s.gamma(:)')
             optimizableVariable('n_diff', s.n_diff(:)', 'Type','integer')
             optimizableVariable('w_hour', s.w_hour(:)')
             optimizableVariable('w_ema',  s.w_ema(:)')
             optimizableVariable('w_mom',  s.w_mom(:)')
             optimizableVariable('w_dv',   s.w_dv(:)')
             optimizableVariable('w_iv',   s.w_iv(:)')
             optimizableVariable('w_hurst',s.w_hurst(:)') ];

    runs_per_k = 1;
    if isfield(job.budget, 'runs_per_k'), runs_per_k = job.budget.runs_per_k; end
    K_values = job.K_values(:)';
    per_K = struct('K', {}, 'sep_score', {}, 'z', {}, 'n_blobs', {}, 'degenerate', {}, ...
                   'params', {}, 'blob_pf', {}, 'blob_z', {}, 'seed', {});
    t_all = tic;
    for K = K_values
        obj_best = -inf; pbest = [];
        for r = 1:runs_per_k          % optimizer restarts over the SAME deterministic function
            rng(job.rng_seed + 1000*K + r);              % acquisition randomness only
            obj = @(p) -sgl_objective(p, Xtr, profits, C, nu, K, shifts, job.objective);
            bo = bayesopt(obj, vars, 'MaxObjectiveEvaluations', job.budget.n_trials, ...
                'NumSeedPoints', job.budget.n_seed, 'IsObjectiveDeterministic', true, ...
                'AcquisitionFunctionName', 'expected-improvement-plus', ...
                'UseParallel', false, 'Verbose', 0, 'PlotFcn', []);
            % XAtMinObjective = the OBSERVED minimizer (bestPoint may return a model-based
            % point whose true value was never evaluated — the identity assert needs observed)
            if -bo.MinObjective > obj_best, obj_best = -bo.MinObjective; pbest = bo.XAtMinObjective; end
        end
        ev = eval_winner(pbest, Xtr, profits, C, nu, K, shifts);
        if strcmp(job.objective, 'z'), refit = ev.z; else, refit = ev.sep; end
        assert(abs(refit - obj_best) < 1e-6 || ev.degenerate, ...
            'estimator identity violated: refit %s %.6f != searched %.6f', job.objective, refit, obj_best);
        per_K(end+1) = struct('K', K, 'sep_score', ev.sep, 'z', ev.z, 'n_blobs', ev.n_blobs, ...
            'degenerate', ev.degenerate, 'params', ev.params, 'blob_pf', ev.blob_pf, ...
            'blob_z', ev.blob_z, 'seed', ev.seed);
        fprintf('  K=%2d  sep=%.2f  z=%.3f  blobs=%d  (%s sig=%.1f k=%d)  [%d runs, %.0fs]\n', K, ...
            ev.sep, ev.z, ev.n_blobs, ev.params.kernel, ev.params.sigma, ev.params.k_nbrs, ...
            runs_per_k, toc(t_all));
        if isfield(job, 'progress_path')     % incremental per-K checkpoint (survives a mid-run death)
            pfid = fopen(job.progress_path, 'a');
            fprintf(pfid, '%s\n', jsonencode(struct('job_hash', job.job_hash, 'K', K, ...
                'sep', ev.sep, 'z', ev.z, 'n_blobs', ev.n_blobs, ...
                'kernel', ev.params.kernel, 'elapsed_s', toc(t_all))));
            fclose(pfid);
        end
    end

    % ── selection under the PINNED selector (no post-hoc column-picking) ───────────────
    if strcmp(job.selector, 'z'), vals = [per_K.z]; else, vals = [per_K.sep_score]; end
    [~, isel] = max(vals);
    out = struct();
    out.job_hash_echo = job.job_hash; out.side = job.side; out.n_train = N;
    out.window_counts = M.counts(:)';
    out.per_K = per_K;                                   % K order — a report, not a ranking
    out.selector = job.selector; out.selected = per_K(isel);
    out.n_evals_total = numel(K_values) * runs_per_k * job.budget.n_trials;   % realized width
    out.objective = job.objective;
    out.pc_echo = struct('windows', job.windows, 'embargo', job.embargo, ...
        'min_window_side', job.min_window_side, 'fit', job.fit, 'null', nu, ...
        'objective', job.objective, 'selector', job.selector, 'budget', job.budget);
    out.engine_stamp = struct('name', 'matlab_sgl', 'version', version, 'git', 'server');
    out.elapsed_s = toc(t_all);
    fid = fopen(job.result_path, 'w'); fprintf(fid, '%s', jsonencode(out)); fclose(fid);
    fprintf('SGL search %s: SELECTED (by %s) K=%d sep=%.2f z=%.3f | width %d evals | %.0fs\n', ...
        job.side, job.selector, out.selected.K, out.selected.sep_score, out.selected.z, ...
        out.n_evals_total, out.elapsed_s);
end


%% ── the deterministic objective + the identical final evaluation ──────────────────────
function v = sgl_objective(p, X, profits, C, nu, K, shifts, objective)
    try
        bid = fit_soft_cfg(p, K, X, C, sgl_param_seed(p, K));
        if strcmp(objective, 'z')                        % the manual tierB objective (tb_z_soft):
            R = sep_z(bid, profits, shifts, nu.min_trades, nu.pf_floor, nu.pf_cap);
            v = R.z;                                     % z vs the CRN null (one shift vector, all evals)
        else                                             % the IS separation score (main_sgl_is)
            v = sep_blobs(bid, profits, nu.min_trades, nu.pf_floor, nu.pf_cap);
        end
    catch
        v = 0;                                           % failed region — deterministic zero
    end
end

function ev = eval_winner(p, X, profits, C, nu, K, shifts)
    ev.seed = sgl_param_seed(p, K);
    ev.params = struct('kernel', char(p.kernel), 'sigma', p.sigma, 'k_nbrs', p.k_nbrs, ...
        'gamma', p.gamma, 'n_diff', p.n_diff, 'w_hour', p.w_hour, 'w_ema', p.w_ema, ...
        'w_mom', p.w_mom, 'w_dv', p.w_dv, 'w_iv', p.w_iv, 'w_hurst', p.w_hurst, 'K', K);
    try
        bid = fit_soft_cfg(p, K, X, C, ev.seed);         % SAME fit the objective evaluated
    catch
        ev.sep = 0; ev.z = 0; ev.degenerate = true; ev.n_blobs = 0;
        ev.blob_pf = []; ev.blob_z = []; return;
    end
    ev.sep = sep_blobs(bid, profits, nu.min_trades, nu.pf_floor, nu.pf_cap);
    R = sep_z(bid, profits, shifts, nu.min_trades, nu.pf_floor, nu.pf_cap);
    ev.z = R.z; ev.degenerate = R.degenerate;
    ev.n_blobs = numel(unique(bid(bid > 0)));
    ev.blob_pf = R.blob_pf(:)'; ev.blob_z = R.blob_z(:)';
end
