function [bid, Sa] = fit_soft_cfg(p, K, Xtr, C, seed)
%FIT_SOFT_CFG  THE single soft-SGL fit. Search objective, search final eval, and the
%   certification readout all call THIS function, so the searched, reported, and
%   certified quantities are the same estimator. (The campaign's z=12 -> 2.96 collapse
%   was an estimator-identity failure: the search fitted with Replicates=1 against the
%   ambient global RNG stream — a function of (params, stream position), irreproducible
%   from params alone — while declaring IsObjectiveDeterministic to bayesopt.)
%
%   Body = tierB_readout.m/tierB_gate_completion.m fit_soft/fit_seed, verbatim:
%   seeded LOCAL stream (restored on exit), robust_eigs (NaN-safe, v0.6.2 fix),
%   kmeans with C.kmeans_reps replicates + EmptyAction singleton, k_nbrs clamped to
%   N-1, dust extraction with the frozen floors. No try/catch — callers decide how
%   a failure is handled (objective: score 0; readout: propagate with diagnostics).
%
%   C: struct(kmeans_reps, n_floor, indeg_q) — from the job contract, never precommit().
    w  = [p.w_hour, p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst];
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
