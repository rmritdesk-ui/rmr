# Release Notes — RMR Platform 5.1.0-commercial-cb1

RMR Platform v5.1 Commercial Candidate preserves the complete v5.1 RC1/RC2 application and corrects the Windows/Docker v5.0 preflight version mismatch proven by the first real RC2 field test.

## Field evidence carried forward

- RC1 Windows post-start health gate failed on a transient closed connection; RC1 automatic rollback restored v5.0.
- RC2 added bounded readiness polling, internal/host health checks, diagnostics, and verified rollback.
- RC2's first real Windows preflight showed v5.0 container `running`, Docker health `healthy`, restart count `0`, host HTTP 200/healthy, and internal health healthy.
- RC2 nevertheless rejected v5.0 because `.env` expected `5.0.0-rc1` while `/api/health` reported `5.0.0-rc.1`.
- RC2 stopped at preflight, so rollback was not required and v5.0 remained untouched.

## RC3 correction

- normalizes only the known v5.0 `5.0.0-rc1` / `5.0.0-rc.1` metadata pair;
- preserves exact version validation for RC3 and unrelated versions;
- requires host and internal versions to agree after normalization;
- records comparable versions and compatibility status in readiness diagnostics;
- preserves RC2 bounded polling, transient Windows HTTP handling, diagnostics, safety backup, additive migration, and verified rollback;
- applies the same narrowly scoped v5.0 compatibility rule to the Linux readiness helper.

## Application functionality

All v5.1 client, onboarding, tenant-isolation, Client 360, CRM, forecasting, website, Solutions Center, Training, ProspectIQ, Partner Economics, password recovery and permission corrections remain intact.

## Certification boundary

Application regressions and RC3 source/model checks passed in the build environment. Windows Docker Desktop is not available in this environment, so the exact RC3 ZIP still requires the external Windows v5.0-to-RC3 upgrade test before Hasan handoff.
