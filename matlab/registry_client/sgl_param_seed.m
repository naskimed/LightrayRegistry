function sd = sgl_param_seed(p, K)
%SGL_PARAM_SEED  djb2(KEY) mod 2^31-1 — the engine's validated KEY->seed convention
%   (param_hash.m / tierB hash_key, verbatim; KEY != seed doctrine). Used as the
%   per-evaluation kmeans seed so every fit is a deterministic function of its params
%   — which is what makes IsObjectiveDeterministic TRUE and search==readout identity
%   possible. CONSCIOUS EXCEPTION to "MATLAB never hashes": seed derivation is
%   engine-native RNG plumbing intrinsic to the validated BelkaSGL pipeline, not
%   registry identity/integrity hashing (which stays Python-side). The %.4f/%.3f
%   truncation means params differing past those decimals share a seed — acceptable
%   for seeding (seed identity is not config identity), inherited from the manual
%   pipeline unchanged.
    key = sprintf('s|%s|%.4f|%d|%.4f|%d|%d|%.3f%.3f%.3f%.3f%.3f%.3f', char(p.kernel), ...
        p.sigma, p.k_nbrs, p.gamma, p.n_diff, K, ...
        p.w_hour, p.w_ema, p.w_mom, p.w_dv, p.w_iv, p.w_hurst);
    sd = 5381;
    for c = double(key), sd = mod(sd*33 + c, 2^31 - 1); end
end
