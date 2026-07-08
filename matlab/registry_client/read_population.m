function [features_raw, profits, dates] = read_population(parquet_path, side)
%READ_POPULATION  Registry population parquet -> the shapes the SGL sweep consumes.
%   Replaces read_belka_config for registry-native populations. Returns, per side:
%     features_raw : [N x 6]  = [hour, ema, mom, dv, iv, hurst]  (raw; preprocess_fit standardizes)
%     profits      : [N x 1]
%     dates        : {N x 1} cellstr (entry timestamps)
%   parquetread only — MATLAB never hashes (the Python bridge does at ingest).
    T = parquetread(parquet_path);
    m = strcmp(string(T.side), side);
    Ts = T(m, :);
    features_raw = double([Ts.f_hour, Ts.f_ema, Ts.f_mom, Ts.f_dv, Ts.f_iv, Ts.f_hurst]);
    profits = double(Ts.profit);
    dates   = cellstr(string(Ts.entry_ts));
    fprintf('read_population: %s side, %d trades\n', side, numel(profits));
end
