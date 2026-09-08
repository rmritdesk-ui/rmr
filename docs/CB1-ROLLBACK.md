# Rollback Instructions

Correction Build 1 never overwrites the existing v5.1 Commercial Candidate folder.

## Automatic rollback

The upgrade script attempts rollback automatically if CB1 does not pass its readiness and version gates. It captures diagnostics before rollback and then verifies the previous `5.1.0-commercial-rc1` health endpoint.

## Manual verified rollback

1. Leave Docker Desktop running.
2. In the Correction Build 1 folder, double-click `ROLLBACK-TO-V5.1-CANDIDATE.bat`.
3. If prompted, select the previous v5.1 candidate folder.
4. The script stops CB1, starts the previous candidate and polls `/api/health` until it confirms `5.1.0-commercial-rc1` is healthy.
5. Do not delete CB1 data or the prior candidate until evidence has been reviewed.

If rollback cannot be verified, run `COLLECT-DIAGNOSTICS-CB1.bat` and provide the newest diagnostic file to RMR/ChatGPT.
