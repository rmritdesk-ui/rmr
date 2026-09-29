const API = "/api/cb1";

let tenants = [];
let tenantId = "";
let currentTab = "readiness";
let socialItems = new Map();

const tabs = [
  ["readiness", "Commercial Readiness"],
  ["access", "Client Access"],
  ["orders", "Order Forms & Entitlements"],
  ["custody", "Data Custody & Export"],
  ["email", "Connected Email"],
  ["campaigns", "AI Outreach & Drip"],
  ["social", "Social Content Copy/Paste"],
  ["health", "System Health"],
];

const $ = (s) => document.querySelector(s);

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );

async function api(path, opt = {}) {
  const r = await fetch(API + path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-RMR-Request": "1",
      ...(opt.headers || {}),
    },
    ...opt,
  });

  let d = {};

  try {
    d = await r.json();
  } catch {}

  if (!r.ok) {
    throw new Error(d.detail || d.error || r.statusText);
  }

  return d;
}

function msg(text, type = "info") {
  $("#notice").innerHTML = `<div class="cb1-alert ${type}">${esc(text)}</div>`;

  setTimeout(() => {
    if ($("#notice")) {
      $("#notice").innerHTML = "";
    }
  }, 7000);
}

function fmt(x) {
  return x ? new Date(x).toLocaleString() : "";
}

function card(label, value, detail = "", state = "") {
  return `
    <article class="cb1-card ${state}">
      <small>${esc(label)}</small>
      <strong>${esc(value)}</strong>
      <p>${esc(detail)}</p>
    </article>
  `;
}

function button(label, action, kind = "", data = {}) {
  const attrs = Object.entries(data)
    .map(([key, value]) => ` data-${key}="${esc(value)}"`)
    .join("");

  return `
    <button
      type="button"
      class="${esc(kind)}"
      data-action="${esc(action)}"
      ${attrs}>
      ${esc(label)}
    </button>
  `;
}

function setContent(h) {
  $("#content").innerHTML = h;
}

function renderTabs() {
  $("#tabs").innerHTML = tabs
    .map(
      ([id, label]) => `
    <button
      type="button"
      class="cb1-tab ${currentTab === id ? "active" : ""}"
      data-tab="${esc(id)}">
      ${esc(label)}
    </button>
  `,
    )
    .join("");
}

async function init() {
  try {
    const me = await api("/me");

    if (!["RMR_OWNER", "OWNER", "SUPER_ADMIN"].includes(me.user.role)) {
      throw new Error("RMR Owner access required.");
    }

    tenants = (await api("/tenants")).tenants;

    $("#tenant").innerHTML = tenants
      .map(
        (t) => `
      <option value="${esc(t.id)}">
        ${esc(t.name)}
      </option>
    `,
      )
      .join("");

    /*
     * Preserve the tenant selected from Client 360.
     */
    const preferredTenant = localStorage.getItem("rmr_selected_tenant");

    const selected = tenants.find(
      (t) => String(t.id) === String(preferredTenant),
    );

    tenantId = selected?.id || tenants[0]?.id || "";

    if (tenantId) {
      $("#tenant").value = tenantId;
    }

    $("#tenant").addEventListener("change", (e) => {
      tenantId = e.target.value;

      localStorage.setItem("rmr_selected_tenant", tenantId);

      showTab(currentTab);
    });

    renderTabs();

    const requested = location.hash.slice(1) || "readiness";

    await showTab(
      tabs.some(([id]) => id === requested) ? requested : "readiness",
    );
  } catch (e) {
    setContent(`
      <h1>Commercial controls unavailable</h1>
      <p>${esc(e.message)}</p>
    `);
  }
}

async function showTab(id) {
  currentTab = id;

  location.hash = id;

  renderTabs();

  setContent("<h1>Loading...</h1>");

  try {
    if (id === "readiness") {
      await readiness();
    }

    if (id === "access") {
      await access();
    }

    if (id === "orders") {
      await orders();
    }

    if (id === "custody") {
      await custody();
    }

    if (id === "email") {
      await email();
    }

    if (id === "campaigns") {
      await campaigns();
    }

    if (id === "social") {
      await social();
    }

    if (id === "health") {
      await health();
    }
  } catch (e) {
    setContent(`
      <h1>Unable to load</h1>
      <div class="cb1-alert error">
        ${esc(e.message)}
      </div>
    `);
  }
}

async function readiness() {
  const d = await api("/commercial-readiness");

  const t = d.tenants.find((x) => String(x.tenant_id) === String(tenantId));

  let h = `
    <h1>Commercial Readiness</h1>

    <p class="lead">
      Objective gates for
      ${esc(t?.name || "selected client")}.
      A green application health check does not override
      a blocked commercial workflow.
    </p>

    <div class="cb1-grid">

      ${card(
        "Release",
        d.release,
        "Packaged frontend and backend must match",
        "good",
      )}

      ${card(
        "Database",
        d.database_backend,
        d.database_backend === "postgresql"
          ? "Production database selected."
          : "SQLite pilot; PostgreSQL certification remains required.",
        d.database_backend === "postgresql" ? "good" : "warn",
      )}

      ${card(
        "Readiness",
        t?.readiness.readiness_pct + "%",
        "Calculated from objective evidence",
        t?.readiness.go_live_complete ? "good" : "bad",
      )}

    </div>

    <h2>Client gates</h2>

    <div class="cb1-list">
  `;

  h += (t?.readiness.gates || [])
    .map(
      (g) => `
      <div>
        <span class="badge ${g.pass ? "good" : g.external ? "warn" : "bad"}">
          ${g.pass ? "PASS" : g.external ? "EXTERNAL" : "BLOCKED"}
        </span>

        <b>${esc(g.label)}</b>

        <p>${esc(g.detail)}</p>
      </div>
    `,
    )
    .join("");

  h += `
    </div>

    <h2>External activation dependencies</h2>

    <ul>
      ${d.external_dependencies.map((x) => `<li>${esc(x)}</li>`).join("")}
    </ul>
  `;

  setContent(h);
}

async function access() {
  const d = await api(`/tenants/${tenantId}/client-admins`);

  let h = `
    <h1>Client Administrator Access</h1>

    <p class="lead">
      Provision the first client administrator,
      track activation evidence,
      resend or reset access,
      and revoke access when required.
    </p>

    <section class="cb1-panel">

      <h2>Invite administrator</h2>

      <div class="fields">

        <label>
          Full name
          <input id="admin-name">
        </label>

        <label>
          Email
          <input id="admin-email" type="email">
        </label>

      </div>

      ${button("Create Invitation", "invite-admin", "primary")}

    </section>

    <section class="cb1-panel">

      <h2>Administrators and invitations</h2>

      <table>

        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Status</th>
            <th>Last sent</th>
            <th>Actions</th>
          </tr>
        </thead>

        <tbody>

          ${
            d.items
              .map(
                (x) => `

              <tr>

                <td>
                  ${esc(x.full_name)}
                </td>

                <td>
                  ${esc(x.email)}
                </td>

                <td>
                  <span class="badge ${
                    x.status === "ACTIVATED"
                      ? "good"
                      : x.status === "REVOKED"
                        ? "bad"
                        : "warn"
                  }">
                    ${esc(x.status)}
                  </span>
                </td>

                <td>
                  ${fmt(x.last_sent_at)}
                </td>

                <td>

                  ${
                    x.status !== "ACTIVATED"
                      ? button("Resend", "resend-admin", "", { id: x.id })
                      : button("Reset access", "reset-admin", "", { id: x.id })
                  }

                  ${button("Revoke", "revoke-admin", "danger", { id: x.id })}

                </td>

              </tr>

            `,
              )
              .join("") ||
            `
              <tr>
                <td colspan="5">
                  No administrator has been provisioned.
                </td>
              </tr>
            `
          }

        </tbody>

      </table>

    </section>
  `;

  setContent(h);
}

async function inviteAdmin() {
  try {
    const d = await api(`/tenants/${tenantId}/client-admins/invite`, {
      method: "POST",
      body: JSON.stringify({
        full_name: $("#admin-name").value,
        email: $("#admin-email").value,
      }),
    });

    await navigator.clipboard.writeText(d.activation_url);

    msg(
      "Invitation created. The activation link was copied to the clipboard.",
      "good",
    );

    access();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function resendAdmin(id) {
  try {
    const d = await api(`/client-admins/${id}/resend`, {
      method: "POST",
      body: "{}",
    });

    await navigator.clipboard.writeText(d.activation_url);

    msg("New activation link copied.", "good");

    access();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function resetAdmin(id) {
  try {
    const d = await api(`/client-admins/${id}/reset`, {
      method: "POST",
      body: "{}",
    });

    await navigator.clipboard.writeText(d.reset_url);

    msg("Reset link copied.", "good");

    access();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function revokeAdmin(id) {
  if (!confirm("Revoke this administrator access record?")) {
    return;
  }

  try {
    await api(`/client-admins/${id}/revoke`, {
      method: "POST",
      body: "{}",
    });

    msg("Access revoked.", "good");

    access();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function orders() {
  const d = await api(`/tenants/${tenantId}/order-forms`);

  let h = `
    <h1>Order Forms & Module Entitlements</h1>

    <p class="lead">
      The MSA governs all modules;
      an RMR-controlled Order Form activates
      commercial access.
    </p>

    <section class="cb1-panel">

      <h2>Record Order Form</h2>

      <div class="fields">

        <label>
          Order reference
          <input
            id="order-ref"
            placeholder="OF-2026-001">
        </label>

        <label>
          Effective date
          <input
            id="order-date"
            type="date">
        </label>

      </div>

      <label>
        Activated modules
      </label>

      <div class="checks">

        ${[
          "crm",
          "piq",
          "adaptive_research",
          "email",
          "campaigns",
          "website",
          "social_content",
          "training",
          "payments",
          "reporting",
        ]
          .map(
            (x) => `

            <label>
              <input
                type="checkbox"
                name="module"
                value="${x}">
              ${x.replaceAll("_", " ")}
            </label>

          `,
          )
          .join("")}

      </div>

      ${button("Record Signed Order Form", "create-order", "primary")}

    </section>

    <section class="cb1-panel">

      <h2>Recorded Orders</h2>

      ${
        d.items
          .map(
            (o) => `

          <div class="order">

            <b>
              ${esc(o.reference)}
            </b>

            <span class="badge good">
              ${esc(o.status)}
            </span>

            <small>
              ${esc(o.effective_date || "")}
            </small>

            <p>
              ${o.entitlements
                .map(
                  (e) => `
                  <span class="chip">
                    ${esc(e.module_key)}
                  </span>
                `,
                )
                .join("")}
            </p>

          </div>

        `,
          )
          .join("") || "<p>No Order Form recorded.</p>"
      }

    </section>
  `;

  setContent(h);
}

async function createOrder() {
  try {
    const ents = [...document.querySelectorAll("[name=module]:checked")].map(
      (x) => ({
        module_key: x.value,
        enabled: true,
      }),
    );

    await api(`/tenants/${tenantId}/order-forms`, {
      method: "POST",
      body: JSON.stringify({
        reference: $("#order-ref").value,
        effective_date: $("#order-date").value || null,
        signed: true,
        entitlements: ents,
      }),
    });

    msg("Order Form and entitlements recorded.", "good");

    orders();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function custody() {
  const d = await api("/custody/status");

  let h = `
    <h1>RMR Owner Data Custody Access</h1>

    <p class="lead">
      RMR-only, separately identified,
      audited access for support,
      recovery, legal response and customer data return.
      Default access is read-only and expires after
      15 minutes.
    </p>

    <div class="cb1-grid">

      ${card(
        "Authority",
        d.authorized_user
          ? "Assigned to this RMR Owner"
          : d.claimed
            ? "Assigned to another owner"
            : "Not claimed",
        "Only one RMR Owner may hold custody authority",
        d.authorized_user ? "good" : "warn",
      )}

      ${card(
        "Multi-factor authentication",
        d.mfa_enrolled ? "Verified" : "Enrollment required",
        "Required before a custody session can start",
        d.mfa_enrolled ? "good" : "warn",
      )}

    </div>
  `;

  if (!d.claimed) {
    h += button("Claim Data Custody Authority", "claim-custody", "primary");
  }

  if (d.authorized_user && !d.mfa_enrolled) {
    h += `
      <section class="cb1-panel">

        <h2>
          Enroll multi-factor authentication
        </h2>

        ${button("Generate authenticator secret", "enroll-mfa", "primary")}

        <div id="mfa-enroll"></div>

      </section>
    `;
  }

  if (d.authorized_user && d.mfa_enrolled) {
    h += `
      <section class="cb1-panel">

        <h2>
          Start secure tenant session
        </h2>

        <div class="fields">

          <label>
            Authenticator code
            <input
              id="mfa-code"
              inputmode="numeric">
          </label>

          <label>
            Required access reason
            <input
              id="custody-reason"
              placeholder="Customer-requested data export">
          </label>

        </div>

        ${button("Verify MFA", "step-up", "primary")}

        ${button("Start 15-minute read-only session", "start-custody")}

      </section>

      <section class="cb1-panel">

        <h2>
          Data return and offboarding
        </h2>

        ${button(
          "Create audited customer-data export",
          "create-export",
          "primary",
        )}

        ${button("Open 30-day offboarding case", "open-offboarding")}

        <div id="export-result"></div>

      </section>
    `;
  }

  setContent(h);
}

async function claimCustody() {
  try {
    await api("/custody/claim", {
      method: "POST",
      body: "{}",
    });

    msg("Data Custody Authority assigned.", "good");

    custody();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function enrollMfa() {
  try {
    const d = await api("/custody/mfa/enroll", {
      method: "POST",
      body: "{}",
    });

    $("#mfa-enroll").innerHTML = `
      <p>
        Enter this secret in Microsoft Authenticator,
        Google Authenticator or another TOTP app:
      </p>

      <code>
        ${esc(d.secret)}
      </code>

      <div class="fields">

        <label>
          Current 6-digit code
          <input id="verify-mfa">
        </label>

      </div>

      ${button("Verify enrollment", "verify-mfa", "primary")}
    `;
  } catch (e) {
    msg(e.message, "error");
  }
}

async function verifyMfa() {
  try {
    await api("/custody/mfa/verify", {
      method: "POST",
      body: JSON.stringify({
        code: $("#verify-mfa").value,
      }),
    });

    msg("Multi-factor authentication verified.", "good");

    custody();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function stepUp() {
  try {
    await api("/custody/step-up", {
      method: "POST",
      body: JSON.stringify({
        code: $("#mfa-code").value,
      }),
    });

    msg("MFA step-up accepted for 10 minutes.", "good");
  } catch (e) {
    msg(e.message, "error");
  }
}

async function startCustody() {
  try {
    await api(`/tenants/${tenantId}/custody/start`, {
      method: "POST",
      body: JSON.stringify({
        reason: $("#custody-reason").value,
      }),
    });

    sessionStorage.setItem("rmr-custody-tenant", tenantId);

    document.body.classList.add("custody-active");

    msg("Read-only custody session started. All activity is audited.", "good");
  } catch (e) {
    msg(e.message, "error");
  }
}

async function createExport() {
  try {
    const d = await api(`/tenants/${tenantId}/exports`, {
      method: "POST",
      body: "{}",
    });

    $("#export-result").innerHTML = `
      <p>
        Export complete. SHA-256:
        <code>
          ${esc(d.job.sha256)}
        </code>
      </p>

      <a
        class="button"
        href="${API}/exports/${d.job.id}/download">
        Download export
      </a>
    `;

    msg("Audited export created.", "good");
  } catch (e) {
    msg(e.message, "error");
  }
}

async function openOffboarding() {
  try {
    const d = await api(`/tenants/${tenantId}/offboarding`, {
      method: "POST",
      body: JSON.stringify({
        notes: "Customer offboarding initiated by RMR Owner.",
      }),
    });

    msg(
      "Offboarding case opened through " + fmt(d.case.export_deadline) + ".",
      "good",
    );
  } catch (e) {
    msg(e.message, "error");
  }
}

async function email() {
  const d = await api(`/tenants/${tenantId}/providers`);

  let h = `
    <h1>Connected Business Email</h1>

    <p class="lead">
      RMR orchestrates approved messages;
      the client business mailbox remains the sender.
      Microsoft and Google require provider app credentials
      and customer authorization.
      Other supported providers use secure SMTP/IMAP.
    </p>

    <section class="cb1-panel">

      <h2>Add connection</h2>

      <div class="fields">

        <label>
          Provider
          <select id="provider">
            <option>MOCK</option>
            <option>MICROSOFT</option>
            <option>GOOGLE</option>
            <option>SMTP_IMAP</option>
          </select>
        </label>

        <label>
          Sender email
          <input
            id="sender-email"
            type="email">
        </label>

        <label>
          Sender name
          <input id="sender-name">
        </label>

        <label>
          Physical postal address
          <input id="physical-address">
        </label>

        <label>
          SMTP host
          <input id="smtp-host">
        </label>

        <label>
          SMTP port
          <input
            id="smtp-port"
            value="587">
        </label>

        <label>
          Username
          <input id="smtp-user">
        </label>

        <label>
          Password
          <input
            id="smtp-pass"
            type="password">
        </label>

      </div>

      ${button("Save Connection", "save-provider", "primary")}

    </section>

    <section class="cb1-panel">

      <h2>Connections</h2>

      <table>

        <thead>
          <tr>
            <th>Provider</th>
            <th>Sender</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>

        <tbody>

          ${
            d.items
              .map(
                (x) => `

              <tr>

                <td>
                  ${esc(x.provider)}
                </td>

                <td>
                  ${esc(x.sender_email)}
                </td>

                <td>
                  <span class="badge ${
                    x.status === "ACTIVE" ? "good" : "warn"
                  }">
                    ${esc(x.status)}
                  </span>
                </td>

                <td>

                  ${button("Test", "test-provider", "", { id: x.id })}

                  ${
                    ["MICROSOFT", "GOOGLE"].includes(x.provider)
                      ? button("Authorize", "authorize-provider", "", {
                          id: x.id,
                        })
                      : ""
                  }

                  ${button("Disconnect", "disconnect-provider", "danger", {
                    id: x.id,
                  })}

                </td>

              </tr>

            `,
              )
              .join("") ||
            `
              <tr>
                <td colspan="4">
                  No connected mailbox.
                </td>
              </tr>
            `
          }

        </tbody>

      </table>

    </section>
  `;

  setContent(h);
}

async function saveProvider() {
  try {
    const provider = $("#provider").value;

    const cfg = {
      smtp_host: $("#smtp-host").value,

      smtp_port: Number($("#smtp-port").value || 587),

      starttls: true,
    };

    const credentials = {
      username: $("#smtp-user").value,

      password: $("#smtp-pass").value,
    };

    await api(`/tenants/${tenantId}/providers`, {
      method: "POST",

      body: JSON.stringify({
        provider,
        sender_email: $("#sender-email").value,
        sender_name: $("#sender-name").value,
        physical_address: $("#physical-address").value,
        config: cfg,
        credentials,
      }),
    });

    msg("Connection saved. Test or authorize it before campaign use.", "good");

    email();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function testProvider(id) {
  try {
    const d = await api(`/provider-connections/${id}/test`, {
      method: "POST",
      body: "{}",
    });

    msg(d.detail, d.status === "ACTIVE" ? "good" : "warn");

    email();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function authorizeProvider(id) {
  try {
    const d = await api(`/provider-connections/${id}/authorize`);

    location.href = d.authorization_url;
  } catch (e) {
    msg(e.message, "warn");
  }
}

async function disconnectProvider(id) {
  try {
    await api(`/provider-connections/${id}`, {
      method: "DELETE",
    });

    msg("Connection disconnected and stored credentials removed.", "good");

    email();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function campaigns() {
  const [cs, ps, wh] = await Promise.all([
    api(`/tenants/${tenantId}/campaigns`),
    api(`/tenants/${tenantId}/providers`),
    api("/worker/health"),
  ]);

  let h = `
    <h1>AI Outreach & Drip</h1>

    <p class="lead">
      Generate from supported facts,
      preview/edit,
      human-approve the exact content,
      schedule it,
      and stop future sequence activity on reply,
      bounce or unsubscribe.
    </p>

    <div class="cb1-grid">

      ${card(
        "Worker",
        wh.status,
        wh.heartbeat_at
          ? "Last heartbeat " + fmt(wh.heartbeat_at)
          : "No heartbeat",
        wh.status === "HEALTHY" ? "good" : "bad",
      )}

      ${card(
        "Active email connections",
        ps.items.filter((x) => x.status === "ACTIVE").length,
        "Client mailbox is the sender",
      )}

    </div>

    <section class="cb1-panel">

      <h2>Create campaign</h2>

      <div class="fields">

        <label>
          Name
          <input id="campaign-name">
        </label>

        <label>
          Mailbox
          <select id="campaign-provider">

            ${ps.items
              .map(
                (x) => `
                <option value="${esc(x.id)}">
                  ${esc(x.provider)}
                  —
                  ${esc(x.sender_email)}
                </option>
              `,
              )
              .join("")}

          </select>
        </label>

      </div>

      ${button("Create Active Campaign", "create-campaign", "primary")}

    </section>

    <section class="cb1-panel">

      <h2>Generate message</h2>

      <div class="fields">

        <label>
          Campaign
          <select id="message-campaign">

            ${cs.items
              .map(
                (x) => `
                <option value="${esc(x.id)}">
                  ${esc(x.name)}
                </option>
              `,
              )
              .join("")}

          </select>
        </label>

        <label>
          Client name
          <input
            id="client-name"
            value="${esc(
              tenants.find((x) => String(x.id) === String(tenantId))?.name ||
                "",
            )}">
        </label>

        <label>
          Recipient name
          <input id="recipient-name">
        </label>

        <label>
          Recipient email
          <input
            id="recipient-email"
            type="email">
        </label>

        <label>
          CRM record ID
          <input id="crm-id">
        </label>

        <label>
          PIQ record ID
          <input id="piq-id">
        </label>

      </div>

      <label>
        Verified facts (one per line)
        <textarea id="facts"></textarea>
      </label>

      <label>
        Call to action
        <textarea id="cta"></textarea>
      </label>

      ${button("Generate Safe Draft", "generate-message", "primary")}

      <div id="message-editor"></div>

    </section>

    <section class="cb1-panel">

      <h2>Campaigns</h2>

      ${
        cs.items
          .map(
            (x) => `

          <div class="order">

            <b>
              ${esc(x.name)}
            </b>

            <span class="badge ${x.status === "ACTIVE" ? "good" : "warn"}">
              ${esc(x.status)}
            </span>

            ${button(
              x.status === "ACTIVE" ? "Pause" : "Resume",
              "campaign-action",
              "",
              {
                id: x.id,
                act: x.status === "ACTIVE" ? "pause" : "resume",
              },
            )}

          </div>

        `,
          )
          .join("") || "<p>No campaign yet.</p>"
      }

    </section>
  `;

  setContent(h);
}

async function createCampaign() {
  try {
    await api(`/tenants/${tenantId}/campaigns`, {
      method: "POST",

      body: JSON.stringify({
        name: $("#campaign-name").value,

        provider_connection_id: $("#campaign-provider").value || null,

        frequency_hours: 24,
      }),
    });

    msg("Campaign created.", "good");

    campaigns();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function campaignAction(id, act) {
  try {
    await api(`/campaigns/${id}/${act}`, {
      method: "POST",
      body: "{}",
    });

    msg("Campaign " + act + "d.", "good");

    campaigns();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function generateMessage() {
  try {
    const facts = $("#facts")
      .value.split("\n")
      .map((x) => x.trim())
      .filter(Boolean);

    const d = await api("/messages/generate", {
      method: "POST",

      body: JSON.stringify({
        tenant_id: tenantId,

        client_name: $("#client-name").value,

        recipient_name: $("#recipient-name").value,

        recipient_email: $("#recipient-email").value,

        facts,

        cta: $("#cta").value,

        campaign_id: $("#message-campaign").value,

        crm_record_id: $("#crm-id").value || null,

        piq_record_id: $("#piq-id").value || null,
      }),
    });

    $("#message-editor").innerHTML = `
      <h3>
        Preview and edit
      </h3>

      <label>
        Subject
        <input
          id="draft-subject"
          value="${esc(d.subject)}">
      </label>

      <label>
        Body
        <textarea
          id="draft-body"
          rows="10">${esc(d.body)}</textarea>
      </label>

      ${button("Save Draft", "save-draft", "primary")}
    `;

    window._facts = facts;
  } catch (e) {
    msg(e.message, "error");
  }
}

async function saveDraft() {
  try {
    const d = await api("/messages", {
      method: "POST",

      body: JSON.stringify({
        tenant_id: tenantId,

        campaign_id: $("#message-campaign").value || null,

        crm_record_id: $("#crm-id").value || null,

        piq_record_id: $("#piq-id").value || null,

        recipient_email: $("#recipient-email").value,

        subject: $("#draft-subject").value,

        body: $("#draft-body").value,

        supported_facts: window._facts || [],
      }),
    });

    window._message = d.message;

    $("#message-editor").innerHTML += `
      <p>
        Draft saved and linked to the CRM/PIQ record.
      </p>

      ${button("Approve Exact Message", "approve-message", "primary")}
    `;
  } catch (e) {
    msg(e.message, "error");
  }
}

async function approveMessage() {
  try {
    const d = await api(`/messages/${window._message.id}/approve`, {
      method: "POST",

      body: JSON.stringify({
        subject: $("#draft-subject").value,

        body: $("#draft-body").value,

        verified_facts: true,
      }),
    });

    window._message = d.message;

    $("#message-editor").innerHTML += `
      <p>
        <b>Approved.</b>
        Any later content change requires a new approval.
      </p>

      <label>
        Schedule
        <input
          id="schedule-at"
          type="datetime-local">
      </label>

      ${button("Schedule Approved Message", "schedule-message", "primary")}
    `;
  } catch (e) {
    msg(e.message, "error");
  }
}

async function scheduleMessage() {
  try {
    const d = new Date($("#schedule-at").value || Date.now() + 60000);

    await api(`/messages/${window._message.id}/schedule`, {
      method: "POST",

      body: JSON.stringify({
        scheduled_at: d.toISOString(),
      }),
    });

    msg("Approved message scheduled.", "good");
  } catch (e) {
    msg(e.message, "error");
  }
}

async function social() {
  const d = await api(`/tenants/${tenantId}/social-content`);

  socialItems = new Map(d.items.map((x) => [String(x.id), x]));

  let h = `
    <h1>
      Social Content — Copy & Paste
    </h1>

    <p class="lead">
      Generate and organize platform-specific content.
      The client copies and posts it through its own
      Facebook, Instagram, LinkedIn or X account.
      No social API publishes from RMR Global in the
      current approved copy/paste workflow.
    </p>

    <section class="cb1-panel">

      <div class="fields">

        <label>
          Platform
          <select id="social-platform">
            <option>FACEBOOK</option>
            <option>INSTAGRAM</option>
            <option>LINKEDIN</option>
            <option>X</option>
          </select>
        </label>

        <label>
          Title
          <input id="social-title">
        </label>

      </div>

      <label>
        Post
        <textarea
          id="social-post"
          rows="8"></textarea>
      </label>

      <label>
        Hashtags
        <input id="social-tags">
      </label>

      ${button("Save Draft", "save-social", "primary")}

    </section>

    <section class="cb1-panel">

      <h2>Drafts</h2>

      ${
        d.items
          .map(
            (x) => `

          <div class="social">

            <b>
              ${esc(x.platform)}
              —
              ${esc(x.title || "Untitled")}
            </b>

            <textarea readonly>${esc(x.post_text)}</textarea>

            <p>
              ${esc(x.hashtags)}
            </p>

            ${button("Copy Post", "copy-post", "primary", { id: x.id })}

            ${button("Copy Hashtags", "copy-tags", "", { id: x.id })}

            ${
              x.status === "PUBLISHED_MANUALLY"
                ? `
                    <span class="badge good">
                      Published
                    </span>

                    <a
                      href="${esc(x.published_url)}"
                      target="_blank"
                      rel="noopener">
                      View
                    </a>
                  `
                : button("Mark Published", "mark-social", "", { id: x.id })
            }

          </div>

        `,
          )
          .join("") || "<p>No social content saved.</p>"
      }

    </section>
  `;

  setContent(h);
}

async function saveSocial() {
  try {
    await api("/social-content", {
      method: "POST",

      body: JSON.stringify({
        tenant_id: tenantId,

        platform: $("#social-platform").value,

        title: $("#social-title").value,

        post_text: $("#social-post").value,

        hashtags: $("#social-tags").value,
      }),
    });

    msg("Social draft saved.", "good");

    social();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function copyText(t) {
  try {
    await navigator.clipboard.writeText(t);

    msg("Copied to clipboard.", "good");
  } catch {
    msg("Unable to copy to clipboard.", "error");
  }
}

async function markSocial(id) {
  const url = prompt("Paste the published social post URL:");

  if (!url) {
    return;
  }

  try {
    await api(`/social-content/${id}/published`, {
      method: "POST",

      body: JSON.stringify({
        published_url: url,
      }),
    });

    msg("Published activity recorded.", "good");

    social();
  } catch (e) {
    msg(e.message, "error");
  }
}

async function health() {
  const d = await api("/business-health");

  let h = `
    <h1>System Health</h1>

    <p class="lead">
      ${esc(d.headline)}
    </p>

    <div class="cb1-grid">

      ${d.cards
        .map((c) =>
          card(
            c.label,
            c.state.replaceAll("_", " "),
            c.message + " " + c.action,
            c.state === "HEALTHY"
              ? "good"
              : c.state === "NEEDS_CONFIGURATION"
                ? "warn"
                : "bad",
          ),
        )
        .join("")}

    </div>

    <details class="cb1-panel">

      <summary>
        Technical details
      </summary>

      <pre>
${esc(JSON.stringify(d.technical, null, 2))}
      </pre>

    </details>
  `;

  setContent(h);
}

/*
 * CSP-safe delegated UI actions.
 * No inline onclick handlers.
 */
document.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-tab]");

  if (tab) {
    showTab(tab.dataset.tab);
    return;
  }

  const btn = event.target.closest("[data-action]");

  if (!btn) {
    return;
  }

  const { action, id, act } = btn.dataset;

  if (action === "invite-admin") {
    inviteAdmin();
  }

  if (action === "resend-admin") {
    resendAdmin(id);
  }

  if (action === "reset-admin") {
    resetAdmin(id);
  }

  if (action === "revoke-admin") {
    revokeAdmin(id);
  }

  if (action === "create-order") {
    createOrder();
  }

  if (action === "claim-custody") {
    claimCustody();
  }

  if (action === "enroll-mfa") {
    enrollMfa();
  }

  if (action === "verify-mfa") {
    verifyMfa();
  }

  if (action === "step-up") {
    stepUp();
  }

  if (action === "start-custody") {
    startCustody();
  }

  if (action === "create-export") {
    createExport();
  }

  if (action === "open-offboarding") {
    openOffboarding();
  }

  if (action === "save-provider") {
    saveProvider();
  }

  if (action === "test-provider") {
    testProvider(id);
  }

  if (action === "authorize-provider") {
    authorizeProvider(id);
  }

  if (action === "disconnect-provider") {
    disconnectProvider(id);
  }

  if (action === "create-campaign") {
    createCampaign();
  }

  if (action === "campaign-action") {
    campaignAction(id, act);
  }

  if (action === "generate-message") {
    generateMessage();
  }

  if (action === "save-draft") {
    saveDraft();
  }

  if (action === "approve-message") {
    approveMessage();
  }

  if (action === "schedule-message") {
    scheduleMessage();
  }

  if (action === "save-social") {
    saveSocial();
  }

  if (action === "copy-post") {
    copyText(socialItems.get(String(id))?.post_text || "");
  }

  if (action === "copy-tags") {
    copyText(socialItems.get(String(id))?.hashtags || "");
  }

  if (action === "mark-social") {
    markSocial(id);
  }
});

init();
