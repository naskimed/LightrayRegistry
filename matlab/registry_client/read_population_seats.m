function [features_raw, profits, dates] = read_population_seats(parquet_path, side, feature_names)
%READ_POPULATION_SEATS  Registry population -> [N x D] raw feature matrix for the SEAT
%   featureset (the 12-seat tournament, FS d_max=12). Columns are read BY NAME from the
%   extended population parquet (fc_* catalog features and/or f_* belka features) — the seat
%   list comes from the job contract, chosen by the agent within the cap. The belka6 path
%   (read_population.m) is untouched; this is the parallel N-feature path.
    T = parquetread(parquet_path);
    m = strcmp(string(T.side), side);
    Ts = T(m, :);
    D = numel(feature_names);
    N = height(Ts);
    features_raw = zeros(N, D);
    for j = 1:D
        col = char(string(feature_names(j)));
        assert(any(strcmp(Ts.Properties.VariableNames, col)), ...
            'seat feature "%s" not present in the population parquet', col);
        features_raw(:, j) = double(Ts.(col));
    end
    profits = double(Ts.profit);
    dates   = cellstr(strrep(string(Ts.entry_ts), '-', '.'));
    fprintf('read_population_seats: %s side, %d trades, %d seats [%s]\n', side, N, D, ...
        strjoin(cellstr(string(feature_names)), ','));
end
