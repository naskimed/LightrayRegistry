function sd = seats_param_seed(p, K, D, feat_tag)
%SEATS_PARAM_SEED  djb2(KEY) for the seat featureset — the engine's KEY->seed convention
%   extended with the seat identity (feat_tag = short hash of the ordered seat names), so
%   the same geometry on different seats gets a different deterministic fit seed.
    wparts = cell(1, D);
    for j = 1:D, wparts{j} = sprintf('%.3f', p.(sprintf('w_%d', j))); end
    key = sprintf('t|%s|%.4f|%d|%.4f|%d|%d|%s|%s', char(p.kernel), p.sigma, p.k_nbrs, ...
        p.gamma, p.n_diff, K, feat_tag, strjoin(wparts, ''));
    sd = 5381;
    for c = double(key), sd = mod(sd*33 + c, 2^31 - 1); end
end
