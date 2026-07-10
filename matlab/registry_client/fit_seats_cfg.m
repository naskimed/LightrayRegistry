function [bid, Sa] = fit_seats_cfg(p, K, Xtr, C, seed, D)
%FIT_SEATS_CFG  THE single seat-featureset fit (N-dim twin of fit_soft_cfg — same estimator
%   discipline: seeded local stream, robust_eigs, kmeans replicates + EmptyAction singleton,
%   k_nbrs clamp, dust extraction). Weights w_1..w_D come from the bayesopt point `p`; the
%   search objective, the final evaluation, and the readout all call THIS function.
    w = zeros(1, D);
    for j = 1:D, w(j) = p.(sprintf('w_%d', j)); end
    Xw = Xtr .* w;  N = size(Xw, 1);
    rs = RandStream('mt19937ar', 'Seed', seed);
    prev = RandStream.setGlobalStream(rs);
    clean = onCleanup(@() RandStream.setGlobalStream(prev)); %#ok<NASGU>
    Kk = psd_kernels(Xw, char(p.kernel), p.sigma);
    [W, Sa] = sgl_graph(Xw, Kk, min(p.k_nbrs, N - 1), p.gamma);  W = max(W, 0);
    d  = max(full(sum(W, 2)), 1e-12);
    Di = spdiags(1./sqrt(d), 0, N, N);  Ks = (Di*W*Di);  Ks = (Ks + Ks')/2;
    [V, lam] = robust_eigs(Ks, K + 1, 'LM');
    [lam, ix] = sort(lam, 'descend');  V = V(:, ix);  lam = max(lam, 0);
    Vd = V(:, 2:end) .* (lam(2:end) .^ p.n_diff)';
    rn = max(sqrt(sum(Vd.^2, 2)), 1e-12);
    lab = kmeans(Vd./rn, K, 'Replicates', C.kmeans_reps, 'MaxIter', 300, ...
                 'EmptyAction', 'singleton', 'Display', 'off');
    bid = extract_blobs_dust(lab, Sa, C.n_floor, C.indeg_q);
end
