function registry_sgl_job(job_json)
%REGISTRY_SGL_JOB  The SGL geometry+weight bridge: registry job.json -> result.json.
%
%   Runs the EXACT sgl_full_eval_fixk pipeline (main_sgl_is.m) for one geometry config,
%   calling YOUR validated functions unchanged (preprocess_fit, psd_kernels, sgl_graph,
%   is_eval, separation_score, sep_z). The registry supplies the frozen population + the
%   frozen constants; MATLAB never hashes. Scales to the full tierB search by wrapping this
%   objective in bayesopt over the 11-variable space (kernel, sigma, k_nbrs, gamma, n_diff,
%   w_hour, w_ema, w_mom, w_dv, w_iv, w_hurst) per K.
%
%   job.json fields: belkasgl_path, population_parquet, side, K, params{kernel,sigma,k_nbrs,
%   gamma,n_diff,w_*}, null{n_shuffles,shuffle_seed,pf_floor,pf_cap,min_trades}, result_path,
%   job_hash.
    job = jsondecode(fileread(job_json));
    addpath(job.belkasgl_path);
    if isfolder(fullfile(job.belkasgl_path, 'ICDE'))
        addpath(fullfile(job.belkasgl_path, 'ICDE'));
    end

    [features_raw, profits, dates] = read_population(job.population_parquet, job.side);
    [X, ~] = preprocess_fit(features_raw);        % standardize (+ hour->sincos => 7 cols)

    p = job.params;  K = job.K;  N = size(X, 1);
    % gate = diagnostics only (thresholds minimised — never filters the sep score)
    gate.pf_threshold = 1.0; gate.min_trades_per_cluster = 1;
    gate.min_pf_consistency = 0.0; gate.min_qualifying_trades_total = 1;

    % --- the geometry+weight pipeline (verbatim from sgl_full_eval_fixk) -----------------
    w  = [p.w_hour, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst];   % FEATURE WEIGHTS
    Xw = X .* w;
    K_ker = psd_kernels(Xw, char(p.kernel), p.sigma);
    W  = sgl_graph(Xw, K_ker, p.k_nbrs, p.gamma);
    W  = max(W, 0);
    d  = max(full(sum(W, 2)), 1e-12);
    Dis = spdiags(1./sqrt(d), 0, N, N);
    Ks = (Dis * W * Dis);  Ks = (Ks + Ks') / 2;
    [V, Lam] = eigs(Ks, K + 1, 'LM', struct('tol', 1e-6, 'maxit', 500));
    lam = diag(Lam);  [lam, ix] = sort(lam, 'descend');  V = V(:, ix);  lam = max(lam, 0);
    Vd = V(:, 2:end) .* (lam(2:end) .^ p.n_diff)';
    rn = max(sqrt(sum(Vd.^2, 2)), 1e-12);
    labels = kmeans(Vd ./ rn, K, 'Replicates', 5, 'MaxIter', 300, 'Display', 'off');

    % --- IS separation score (the search objective) -------------------------------------
    [~, ~, n_qual, qual_trades, metrics] = is_eval(labels, profits, dates, gate);
    sep_score = separation_score(metrics, job.null.min_trades, job.null.pf_floor, job.null.pf_cap);

    % --- the GATE quantity: CRN sep_z (null-of-the-max ruler) ----------------------------
    rs = RandStream('mt19937ar', 'Seed', job.null.shuffle_seed);
    shifts = randi(rs, N - 1, job.null.n_shuffles, 1);
    R = sep_z(labels, profits, shifts, job.null.min_trades, job.null.pf_floor, job.null.pf_cap);

    % --- result manifest (Python bridge hashes it at ingest) ----------------------------
    out = struct();
    out.job_hash_echo = job.job_hash;
    out.side = job.side;  out.K = K;  out.n_trades = N;
    out.n_blobs = numel(unique(labels));
    out.sep_score = sep_score;
    out.z = R.z;                          % the gate z (vs the circular-shift null-of-the-max)
    out.degenerate = R.degenerate;
    out.blob_ids = R.blob_ids(:)';  out.blob_z = R.blob_z(:)';  out.blob_pf = R.blob_pf(:)';
    out.params = p;
    out.engine_stamp = struct('name', 'matlab_sgl', 'version', version, 'git', 'server');
    fid = fopen(job.result_path, 'w');
    fprintf(fid, '%s', jsonencode(out));
    fclose(fid);
    fprintf('SGL eval: side=%s K=%d blobs=%d sep_score=%.3f z=%.3f (N=%d)\n', ...
        job.side, K, out.n_blobs, sep_score, R.z, N);
end
