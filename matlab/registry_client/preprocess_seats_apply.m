function X_proc = preprocess_seats_apply(X_raw, params)
%PREPROCESS_SEATS_APPLY  Apply train-fitted seat preprocessing to held-out rows.
    [~, D] = size(X_raw);
    X = X_raw;
    for j = 1:D
        col = X(:, j);
        col(isnan(col)) = params.med_impute(j);
        col = max(min(col, params.win_hi(j)), params.win_lo(j));
        X(:, j) = (col - params.center(j)) / params.scale(j);
    end
    X_proc = X;
end
