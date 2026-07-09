function registry_sgl_job(~)
%REGISTRY_SGL_JOB  DEPRECATED — REMOVED FROM SERVICE 2026-07-09 (audit finding).
%
%   This was the pre-fix single-config evaluator: kmeans Replicates=5 with NO seeded
%   RandStream (ambient global stream), NO window mask (full-sample preprocessing — leaks
%   window rows into the winsorize/median/IQR stats), raw eigs, ad-hoc gate thresholds. It
%   is the exact estimator-identity + leakage bug class that the corrected pipeline fixed;
%   leaving it runnable is a loaded gun. Original body preserved as
%   registry_sgl_job.m.DEPRECATED for reference only.
%
%   USE INSTEAD: registry_sgl_search (bayesopt search) / registry_readout (single-config
%   certification readout) — both on the shared fit_soft_cfg estimator with the mask,
%   param-hash seed, dust extraction, and job-sourced constants.
    error('registry_sgl_job:deprecated', ['registry_sgl_job is DEPRECATED (pre-fix broken ' ...
        'estimator: Replicates=5, ambient RNG, no mask). Use registry_sgl_search / ' ...
        'registry_readout. See registry_sgl_job.m.DEPRECATED for the old body.']);
end
