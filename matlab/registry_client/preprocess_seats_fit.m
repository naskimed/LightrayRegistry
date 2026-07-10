function [X_proc, params] = preprocess_seats_fit(X_raw)
%PREPROCESS_SEATS_FIT  Train-only preprocessing for the SEAT featureset (generic D-dim).
%   Winsorize at the 1st/99th percentile, then robust-scale (center=median, scale=IQR) —
%   the same first two stages as the validated belka pipeline (preprocess_fit.m), WITHOUT
%   the belka-specific stages (hour sin/cos lives in the catalog as hour_sin/hour_cos
%   columns; signed-log is unnecessary once tails are winsorized then IQR-scaled).
%   NaNs (feature warmup) are imputed to the train MEDIAN before winsorizing — a train-only
%   constant, target-blind.
    [~, D] = size(X_raw);
    X = X_raw;
    params.med_impute = zeros(1, D);
    params.win_lo = zeros(1, D); params.win_hi = zeros(1, D);
    params.center = zeros(1, D); params.scale = zeros(1, D);
    for j = 1:D
        col = X(:, j);
        params.med_impute(j) = median(col(~isnan(col)));
        col(isnan(col)) = params.med_impute(j);
        params.win_lo(j) = prctile(col, 1);
        params.win_hi(j) = prctile(col, 99);
        col = max(min(col, params.win_hi(j)), params.win_lo(j));
        params.center(j) = median(col);
        params.scale(j) = iqr(col);
        if params.scale(j) < 1e-10, params.scale(j) = 1; end
        X(:, j) = (col - params.center(j)) / params.scale(j);
    end
    X_proc = X;
    fprintf('Seats preprocessing fit: %d points, %dD (winsorize+robust-scale, train-only)\n', ...
        size(X, 1), D);
end
