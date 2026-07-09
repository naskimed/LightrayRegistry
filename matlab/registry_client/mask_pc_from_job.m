function PCm = mask_pc_from_job(job)
%MASK_PC_FROM_JOB  tierB_mask constants built from the JOB CONTRACT ONLY.
%   Single-sourcing rule: the registry owns constants; engines never read
%   precommit() off whatever BelkaSGL tree happens to be on the MATLAB path
%   (the observed drift class: search taking windows from the job while the
%   readout silently took them from the tree). Both search and readout build
%   their mask through THIS function and echo it in the result manifest.
    PCm.windows = [cellstr(string(job.windows.names(:))), ...
                   cellstr(string(job.windows.starts(:))), ...
                   cellstr(string(job.windows.ends(:)))];
    PCm.embargo_left_d  = job.embargo.left_d;
    PCm.embargo_right_d = job.embargo.right_d;
    if isfield(job, 'exclusions') && ~isempty(job.exclusions.starts)
        PCm.window_exclusions = [cellstr(string(job.exclusions.starts(:))), ...
                                 cellstr(string(job.exclusions.ends(:)))];
    else
        PCm.window_exclusions = cell(0, 2);
    end
    PCm.min_window_side = job.min_window_side;
end
