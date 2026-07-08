function registry_sgl_search(job_json)
%REGISTRY_SGL_SEARCH  The full SGL geometry+weight SEARCH (bayesopt over 11 vars per K).
%
%   Mirrors main_sgl_is.m's sgl_objective_fixk EXACTLY, driven by the registry job contract and
%   run on the registry population. For each K in job.K_values it bayesopt-optimizes
%   {kernel, sigma, k_nbrs, gamma, n_diff, w_hour..w_hurst} to MAXIMIZE the IS separation_score,
%   then fully evaluates the best point to get the gate z (sep_z vs the CRN null-of-the-max) and
%   the per-blob discovery layer. Pools per-K winners, ranks, writes result.json.
%
%   job.json: belkasgl_path, population_parquet, side, K_values[], search{sigma,k_nbrs,gamma,
%   n_diff,w_hour,w_ema,w_mom,w_dv,w_iv,w_hurst = [lo hi]}, budget{n_trials,n_seed}, null{...},
%   rng_seed, result_path, job_hash.
    job = jsondecode(fileread(job_json));
    addpath(job.belkasgl_path);
    if isfolder(fullfile(job.belkasgl_path, 'ICDE')), addpath(fullfile(job.belkasgl_path, 'ICDE')); end

    [features_raw, profits, dates] = read_population(job.population_parquet, job.side);
    [X, ~] = preprocess_fit(features_raw);
    N = size(X, 1);

    % ── window mask: reproduce the manual tierB masked-train (train = complement of the
    %    W1..W4 windows + embargo purge), via YOUR tierB_mask.m unchanged. Search runs on
    %    masked-train ONLY; the windows are held out for the OOS readout. ─────────────────
    win_counts = [];
    if isfield(job, 'windows')
        PC.windows = [cellstr(string(job.windows.names(:))), ...
                      cellstr(string(job.windows.starts(:))), ...
                      cellstr(string(job.windows.ends(:)))];
        PC.embargo_left_d  = job.embargo.left_d;
        PC.embargo_right_d = job.embargo.right_d;
        if isfield(job, 'exclusions') && ~isempty(job.exclusions.starts)
            PC.window_exclusions = [cellstr(string(job.exclusions.starts(:))), ...
                                    cellstr(string(job.exclusions.ends(:)))];
        else
            PC.window_exclusions = cell(0, 2);
        end
        PC.min_window_side = job.min_window_side;
        M = tierB_mask(dates, PC);            % BLOCKS if any window < min_window_side
        win_counts = M.counts(:)';
        fprintf('  masked-train: %d of %d trades held out to windows %s (counts %s)\n', ...
            sum(M.is_train), N, mat2str(1:size(PC.windows,1)), mat2str(win_counts));
        X = X(M.is_train, :); profits = profits(M.is_train); dates = dates(M.is_train);
        N = size(X, 1);
    end
    gate.pf_threshold = 1.0; gate.min_trades_per_cluster = 1;
    gate.min_pf_consistency = 0.0; gate.min_qualifying_trades_total = 1;
    nu = job.null;
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

    K_values = job.K_values(:)';
    per_K = struct('K', {}, 'sep_score', {}, 'z', {}, 'n_blobs', {}, 'degenerate', {}, ...
                   'params', {}, 'blob_pf', {}, 'blob_z', {});
    t_all = tic;
    for K = K_values
        rng(job.rng_seed + K);
        obj = @(p) -sgl_sep(p, X, profits, dates, gate, nu, K);
        bo = bayesopt(obj, vars, 'MaxObjectiveEvaluations', job.budget.n_trials, ...
            'NumSeedPoints', job.budget.n_seed, 'IsObjectiveDeterministic', true, ...
            'AcquisitionFunctionName', 'expected-improvement-plus', ...
            'UseParallel', false, 'Verbose', 0, 'PlotFcn', []);
        sep_best = -bo.MinObjective;
        pbest = bestPoint(bo);
        ev = sgl_full(pbest, X, profits, dates, gate, nu, K);   % z + blobs at the winner
        per_K(end+1) = struct('K', K, 'sep_score', sep_best, 'z', ev.z, ...
            'n_blobs', ev.n_blobs, 'degenerate', ev.degenerate, 'params', ev.params, ...
            'blob_pf', ev.blob_pf, 'blob_z', ev.blob_z);
        fprintf('  K=%2d  sep=%.2f  z=%.3f  blobs=%d  (%s sig=%.1f k=%d)\n', K, sep_best, ...
            ev.z, ev.n_blobs, ev.params.kernel, ev.params.sigma, ev.params.k_nbrs);
    end

    [~, ord] = sort([per_K.sep_score], 'descend');
    per_K = per_K(ord);
    out = struct();
    out.job_hash_echo = job.job_hash; out.side = job.side; out.n_train = N;
    out.window_counts = win_counts;
    out.per_K = per_K; out.best = per_K(1);
    out.engine_stamp = struct('name','matlab_sgl','version',version,'git','server');
    out.elapsed_s = toc(t_all);
    fid = fopen(job.result_path, 'w'); fprintf(fid, '%s', jsonencode(out)); fclose(fid);
    fprintf('SGL search %s: best K=%d sep=%.2f z=%.3f in %.0fs\n', ...
        job.side, out.best.K, out.best.sep_score, out.best.z, out.elapsed_s);
end


% ---- the geometry pipeline (verbatim from sgl_objective_fixk) --------------------------------
function labels = sgl_geom(p, X, K)
    labels = [];
    w  = [p.w_hour, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst];
    Xw = X .* w;  N = size(Xw, 1);
    try, K_ker = psd_kernels(Xw, char(p.kernel), p.sigma); catch, return; end
    try, W = sgl_graph(Xw, K_ker, p.k_nbrs, p.gamma);      catch, return; end
    W = max(W, 0);  d = max(full(sum(W, 2)), 1e-12);
    Dis = spdiags(1./sqrt(d), 0, N, N);  Ks = (Dis * W * Dis);  Ks = (Ks + Ks') / 2;
    try, [V, Lam] = eigs(Ks, K + 1, 'LM', struct('tol',1e-6,'maxit',500)); catch, return; end
    lam = diag(Lam);  [lam, ix] = sort(lam, 'descend');  V = V(:, ix);  lam = max(lam, 0);
    Vd = V(:, 2:end) .* (lam(2:end) .^ p.n_diff)';  rn = max(sqrt(sum(Vd.^2, 2)), 1e-12);
    try, labels = kmeans(Vd ./ rn, K, 'Replicates', 1, 'MaxIter', 300, 'Display', 'off'); catch, labels = []; end
end

function sep = sgl_sep(p, X, profits, dates, gate, nu, K)
    labels = sgl_geom(p, X, K);
    if isempty(labels), sep = 0; return; end
    [~, ~, ~, ~, metrics] = is_eval(labels, profits, dates, gate);
    sep = separation_score(metrics, nu.min_trades, nu.pf_floor, nu.pf_cap);
end

function ev = sgl_full(p, X, profits, dates, gate, nu, K)
    labels = sgl_geom(p, X, K);
    ev.params = struct('kernel', char(p.kernel), 'sigma', p.sigma, 'k_nbrs', p.k_nbrs, ...
        'gamma', p.gamma, 'n_diff', p.n_diff, 'w_hour', p.w_hour, 'w_ema', p.w_ema, ...
        'w_mom', p.w_mom, 'w_dv', p.w_dv, 'w_iv', p.w_iv, 'w_hurst', p.w_hurst, 'K', K);
    if isempty(labels)
        ev.z = 0; ev.degenerate = true; ev.n_blobs = 0; ev.blob_pf = []; ev.blob_z = []; return;
    end
    N = size(X, 1);
    rs = RandStream('mt19937ar', 'Seed', nu.shuffle_seed);
    shifts = randi(rs, N - 1, nu.n_shuffles, 1);
    R = sep_z(labels, profits, shifts, nu.min_trades, nu.pf_floor, nu.pf_cap);
    ev.z = R.z; ev.degenerate = R.degenerate; ev.n_blobs = numel(unique(labels));
    ev.blob_pf = R.blob_pf(:)'; ev.blob_z = R.blob_z(:)';
end
