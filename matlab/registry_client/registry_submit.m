function registry_submit(result_struct, inbox_dir, name)
%REGISTRY_SUBMIT Submit a result manifest to the registry inbox (files ONLY — the engine
%   submission path). Write to staging/, then MOVE into pending/ — atomic on the same
%   filesystem (verified by the week-1 check). Called as the LAST line of run_tonight.m —
%   an explicit push, never a directory watcher (half-written file hazard).
%
%   result_struct must carry: job_hash_echo, block_id, engine_stamp (name/version/git),
%   pc_echo (the PC struct actually threaded through the computation — the bridge diffs it
%   against the registered constants and REJECTS on mismatch), artifacts, trial_batches.
    staging = fullfile(inbox_dir, 'staging');
    pending = fullfile(inbox_dir, 'pending');
    if ~exist(staging, 'dir'); mkdir(staging); end
    if ~exist(pending, 'dir'); mkdir(pending); end

    tmp = fullfile(staging, [name '.json']);
    fid = fopen(tmp, 'w');
    assert(fid > 0, 'registry_submit:open', 'cannot open %s', tmp);
    fwrite(fid, jsonencode(result_struct), 'char');
    fclose(fid);

    ok = movefile(tmp, fullfile(pending, [name '.json']));  % atomic iff same filesystem
    assert(ok, 'registry_submit:rename', 'rename into pending/ failed');
end
