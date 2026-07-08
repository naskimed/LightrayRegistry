function contract = registry_load_contract(json_path)
%REGISTRY_LOAD_CONTRACT Load a frozen contract export (job.json / constants / windowset).
%   Engines NEVER read the event log — only contract exports. jsondecode only; MATLAB never
%   hashes (physical hashes are the Python bridge's job at ingest).
    raw = fileread(json_path);
    contract = jsondecode(raw);
    % hard assertions the shim relies on
    assert(isfield(contract, 'job_hash') || isfield(contract, 'doc_id'), ...
        'registry_load_contract:badContract', 'not a registry contract: %s', json_path);
    if isfield(contract, 'index_base')
        assert(contract.index_base == 0, 'registry_load_contract:indexBase', ...
            'index_base must be 0 (explicit in the contract)');
    end
end
