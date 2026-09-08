# CB1-R2 Rollback Evidence and Boundary

The CB1-R1 Windows field run entered the failure branch because the wrapper misclassified native stderr. The existing rollback architecture then:

1. Stopped and removed the unsuccessful CB1-R1 attempt.
2. Started the untouched v5.1 Commercial Candidate installation.
3. Polled container, internal API, host API, Docker health and version.
4. Reported that the previous v5.1 Commercial Candidate was running and healthy.

That field result proves the inherited automatic rollback architecture operated successfully during the false-failure scenario.

CB1-R2 does not redesign or bypass rollback. It changes only how the migration wrapper determines the Docker process exit code. The same failure branch remains active for real nonzero migration exits and post-migration readiness failures.

A fresh controlled rollback must still be performed against the exact CB1-R2 packaged artifact before Product Owner acceptance. Production is not authorized.
