import { api } from "../api.js";
import { state } from "../state.js";
import {
  $,
  badge,
  empty,
  esc,
  loading,
  modal,
  pageHead,
  setActiveNav,
  syncBillingNavigation,
  statusTone,
  toast,
} from "../ui.js";

let stripeLoaderPromise = null;
let billingRenderSequence = 0;

function loadStripeJs() {
  if (window.Stripe) return Promise.resolve(window.Stripe);
  if (stripeLoaderPromise) return stripeLoaderPromise;

  stripeLoaderPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector("script[data-rmr-stripe-js]");
    if (existing) {
      existing.addEventListener("load", () => resolve(window.Stripe), {
        once: true,
      });
      existing.addEventListener(
        "error",
        () => reject(new Error("Unable to load Stripe.js.")),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.src = "https://js.stripe.com/v3/";
    script.async = true;
    script.dataset.rmrStripeJs = "1";
    script.onload = () => resolve(window.Stripe);
    script.onerror = () => reject(new Error("Unable to load Stripe.js."));
    document.head.appendChild(script);
  }).catch((error) => {
    document.querySelector("script[data-rmr-stripe-js]")?.remove();
    stripeLoaderPromise = null;
    throw error;
  });

  return stripeLoaderPromise;
}

function cardLabel(paymentMethod) {
  if (!paymentMethod) return "Not added";
  const brand = String(paymentMethod.brand || "Card");
  const last4 = String(paymentMethod.last4 || "");
  return `${brand.charAt(0).toUpperCase()}${brand.slice(1)} •••• ${last4}`;
}

function expiryLabel(paymentMethod) {
  if (!paymentMethod?.exp_month || !paymentMethod?.exp_year) return "";
  return `Expires ${String(paymentMethod.exp_month).padStart(2, "0")}/${String(paymentMethod.exp_year).slice(-2)}`;
}

function setupStatusLabel(status) {
  const value = String(status || "not_configured");
  if (value === "ready") return "Ready";
  if (value === "setup_pending") return "Setup pending";
  if (value === "customer_created") return "Customer created";
  return "Payment method required";
}

function clearStripeReturnQuery() {
  const url = new URL(window.location.href);
  const hadReturn =
    url.searchParams.has("setup_intent") ||
    url.searchParams.has("setup_intent_client_secret") ||
    url.searchParams.has("redirect_status") ||
    url.searchParams.has("stripe_billing_return");

  if (!hadReturn) return;

  url.searchParams.delete("setup_intent");
  url.searchParams.delete("setup_intent_client_secret");
  url.searchParams.delete("redirect_status");
  url.searchParams.delete("stripe_billing_return");

  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

async function completeSetupIntent(tenantId, setupIntentId) {
  return api(`/api/tenants/${tenantId}/billing/payment-method/complete`, {
    method: "POST",
    body: { setup_intent_id: setupIntentId },
  });
}

async function runBillingOperation(tenantId, kind, endpoint, body = {}) {
  const key = `rmr-billing-completed:${tenantId}:${kind}`;
  const operation = await api(`/api/tenants/${tenantId}/billing/operations/${kind}`, {
    method: "POST",
    body: { previous_operation_id: sessionStorage.getItem(key) },
  });
  // On timeout/error keep the same server operation for the next attempt.
  let result;
  try {
    result = await api(`/api/tenants/${tenantId}/billing/${endpoint}`, {
      method: "POST", body: { ...body, operation_id: operation.operation_id },
    });
  } catch (error) {
    throw error;
  }
  sessionStorage.setItem(key, operation.operation_id);
  return result;
}

async function finalizeStripeReturnIfPresent(tenantId) {
  const params = new URLSearchParams(window.location.search);
  const setupIntentId = params.get("setup_intent");

  if (!setupIntentId) return false;

  try {
    await completeSetupIntent(tenantId, setupIntentId);
    clearStripeReturnQuery();
    toast("Payment method saved successfully.");
    return true;
  } catch (error) {
    clearStripeReturnQuery();
    toast(error.message || "Unable to complete payment method setup.", "error");
    return false;
  }
}

function paymentMethodCard(data) {
  const paymentMethod = data.payment_method;
  const ready = data.setup_status === "ready" && paymentMethod;

  return `
    <section class="card">
      <div class="list-item">
        <span class="grow">
          <strong>Payment method</strong>
          <small class="muted">
            ${ready ? esc(cardLabel(paymentMethod)) : "No payment method is currently stored in RMR."}
          </small>
          ${ready && expiryLabel(paymentMethod) ? `<small class="muted">${esc(expiryLabel(paymentMethod))}</small>` : ""}
        </span>
        ${badge(ready ? "Saved" : "Required", ready ? "green" : "amber")}
      </div>
      <div style="margin-top:16px">
        ${
          data.can_manage
            ? `<button class="button" id="billing-add-payment-method">${ready ? "Replace Payment Method" : "Add Payment Method"}</button>`
            : `<div class="tiny muted">Only an authorized Client Administrator, or an RMR administrator in an active managed-write session, can change billing details.</div>`
        }
      </div>
    </section>
  `;
}

async function openPaymentMethodModal(data, ctx, isCurrent = () => data.tenant.id === state.selectedTenantId) {
  const tenantId = data.tenant.id;
  if (!tenantId || !isCurrent()) return;

  let setup;
  try {
    setup = await runBillingOperation(tenantId, "setup", "setup-intent");
  } catch (error) {
    toast(error.message || "Unable to start payment method setup.", "error");
    return;
  }

  if (!isCurrent()) return;
  if (!setup.publishable_key || !setup.client_secret) {
    toast("Stripe billing is not configured correctly.", "error");
    return;
  }

  let StripeFactory;
  try {
    StripeFactory = await loadStripeJs();
  } catch (error) {
    toast(error.message, "error");
    return;
  }

  if (!isCurrent()) return;
  if (typeof StripeFactory !== "function") {
    toast("Stripe.js did not initialize.", "error");
    return;
  }

  const stripe = StripeFactory(setup.publishable_key);
  const elements = stripe.elements({
    clientSecret: setup.client_secret,
    appearance: {
      theme: "stripe",
      variables: {
        borderRadius: "8px",
      },
    },
  });

  modal({
    title: data.payment_method
      ? "Replace Payment Method"
      : "Add Payment Method",
    body: `
      <div class="notice-card" style="margin-bottom:16px">
        <strong>Secure payment method setup</strong>
        <p>Your card details are entered directly into Stripe Elements. RMR stores only the Stripe payment-method reference and masked card details.</p>
      </div>
      <form id="billing-payment-form">
        <div id="billing-payment-element"></div>
        <div id="billing-payment-error" class="field-error" role="alert" style="margin-top:12px"></div>
      </form>
    `,
    footer: `
      <button class="button secondary" data-close-modal>Cancel</button>
      <button class="button" id="billing-save-payment-method">Save Payment Method</button>
    `,
    closeOnBackdrop: false,
    onOpen: (root, close) => {
      const paymentElement = elements.create("payment", {
        layout: "tabs",
      });
      paymentElement.mount($("#billing-payment-element", root));

      const saveButton = $("#billing-save-payment-method", root);
      const errorBox = $("#billing-payment-error", root);

      saveButton.addEventListener("click", async () => {
        if (!isCurrent()) { close(); return; }
        if (saveButton.disabled) return;
        saveButton.disabled = true;
        saveButton.textContent = "Saving...";
        errorBox.textContent = "";

        const returnUrl = new URL(window.location.href);
        returnUrl.search = "";
        returnUrl.searchParams.set("stripe_billing_return", "1");
        returnUrl.hash = "#/billing";

        try {
          const result = await stripe.confirmSetup({
            elements,
            confirmParams: {
              return_url: returnUrl.toString(),
            },
            redirect: "if_required",
          });

          if (result.error) {
            errorBox.textContent =
              result.error.message ||
              "Stripe could not save this payment method.";
            saveButton.disabled = false;
            saveButton.textContent = "Save Payment Method";
            return;
          }

          if (!result.setupIntent?.id) {
            errorBox.textContent =
              "Stripe did not return a completed SetupIntent.";
            saveButton.disabled = false;
            saveButton.textContent = "Save Payment Method";
            return;
          }

          if (!isCurrent()) { close(); return; }
          await completeSetupIntent(tenantId, result.setupIntent.id);
          if (!isCurrent()) { close(); return; }
          close();
          toast("Payment method saved successfully.");
          await renderBillingPage(ctx);
        } catch (error) {
          errorBox.textContent =
            error.message || "Unable to save payment method.";
          saveButton.disabled = false;
          saveButton.textContent = "Save Payment Method";
        }
      });
    },
  });
}

function monthlyPanel(data) {
  const m = data.monthly;
  if (!m || data.setup_status !== "ready" || !data.payment_method) return "";
  const amount = (cents) => `$${(cents / 100).toFixed(2)} USD`;
  const labels = {payment_method_required:"Payment Method Required", ready_to_activate:"Review your services",
    activating:"Payment processing", active:"Your services are active", payment_problem:"Payment could not be completed",
    no_billable_services:"No priced monthly services assigned"};
  const services = m.subscription?.services || m.services;
  const total = amount(m.subscription?.monthly_amount_cents ?? m.total_cents);
  const canActivate = data.can_manage && data.subscription_activation_available && ["ready_to_activate", "activating"].includes(m.stage);
  return `<section class="card"><h2>${esc(labels[m.stage] || m.stage)}</h2>
    ${(services || []).map(s => `<div class="list-item"><strong class="grow">${esc(s.name)}</strong><span>${amount(s.amount_cents)}/month</span></div>`).join("")}
    <p><strong>Monthly total: ${total}</strong></p>
    <p>Payment method: ${esc(cardLabel(data.payment_method))}</p>
    ${m.unpriced_services?.length ? `<p class="muted">Included / No monthly charge: ${m.unpriced_services.map(s => esc(s.name)).join(", ")} (unpriced).</p>` : ""}
    ${m.stage === "payment_method_required" ? "<p>Add a payment method to review and activate your paid services. Saving a card alone does not charge you.</p>" : ""}
    ${m.subscription ? `<p>Latest payment: ${esc(m.subscription.last_payment_status)}</p>
      ${m.subscription.current_period_end ? `<p>Next billing date / current period end: ${esc(m.subscription.current_period_end)}</p>` : ""}` : ""}
    ${m.next_cycle ? `<p class="muted">Next billing cycle: $${(m.next_cycle.total_cents / 100).toFixed(2)}/month${m.next_cycle.status !== 'scheduled' ? ' — update pending confirmation' : ''}.${m.next_cycle.effective_date ? ` Effective date: ${esc(m.next_cycle.effective_date)}.` : ''} No change to this paid period.</p>` : ''}
    ${m.stage === "payment_problem" ? "<p>Paid service access is blocked. Update your payment method if needed, then resolve payment if requested. Otherwise contact your billing administrator.</p>" : ""}
    ${canActivate ? `<h3>Review and confirm your monthly services</h3><label><input type="checkbox" id="billing-monthly-consent"> I confirm these services and authorize the monthly charge shown above until cancelled.</label>
      <small class="muted">Sandbox mode. Billing recurs monthly until cancelled.</small>
      <button class="button" id="billing-activate-monthly" disabled>Activate Services &amp; Start Monthly Billing</button>` : ""}
    ${data.can_manage && data.subscription_activation_available && m.subscription?.id && m.subscription?.payment_action_required ? '<button class="button secondary" id="billing-refresh-monthly">Resolve Payment</button>' : ""}
    ${!data.subscription_activation_available && m.billing_required ? '<p>Monthly activation is unavailable. Matching Stripe sandbox keys and an authorized billing administrator are required.</p>' : ""}
    ${m.stage === "active" ? '<a class="button" href="#/home">Go to Dashboard</a>' : ''}
    <p id="billing-monthly-result" role="status" aria-live="polite"></p></section>`;
}

async function finishMonthlyPayment(result, tenantId) {
  if (result.client_secret) {
    const StripeFactory = await loadStripeJs();
    const response = await StripeFactory(result.publishable_key).confirmCardPayment(result.client_secret,
      {payment_method: result.payment_method_id});
    if (response.error) throw new Error(response.error.message || "Payment needs attention. Update your card and retry.");
    return api(`/api/tenants/${tenantId}/billing/subscription/refresh`, {method:"POST"});
  }
  return result;
}

export async function renderBillingPage(ctx) {
  const tenantId = state.selectedTenantId;
  const user = state.user;
  const sequence = ++billingRenderSequence;
  const isCurrent = () => sequence === billingRenderSequence && tenantId === state.selectedTenantId && user === state.user
    && (!state.route || state.route === "billing");
  setActiveNav("billing");

  const page = $("#page");
  page.innerHTML = loading();

  if (!state.selectedTenantId) {
    page.innerHTML = empty(
      "Select a client",
      "Choose a client before opening Billing & Payments.",
    );
    return;
  }

  try {
    await finalizeStripeReturnIfPresent(tenantId);
    if (!isCurrent()) return;

    const data = await api(`/api/tenants/${tenantId}/billing`);
    if (!isCurrent()) return;
    if (data.tenant?.id !== tenantId) throw new Error("Billing response does not match the current client. Reload Billing & Payments.");
    syncBillingNavigation(data);
    const ready = data.setup_status === "ready" && data.payment_method;

    page.innerHTML = `
      ${pageHead(
        "Billing & Payments",
        "Manage the payment method RMR will use for authorized future billing.",
      )}

      <section class="hero-card">
        <div>
          <div class="eyebrow">BILLING SETUP</div>
          <h2>${data.monthly?.stage === "active" ? "Your services are active" : data.monthly?.billing_required ? "Complete your billing setup" : "Billing & Payments"}</h2>
          ${data.monthly?.billing_required ? '<p>Before you can access your RMR services, please add a payment method and activate your assigned services.</p><ol aria-label="Billing setup progress"><li>Add payment method</li><li>Review services</li><li>Confirm monthly billing</li><li>Access services</li></ol>' : ''}
          <h3>${data.monthly?.stage === "active" ? "Access your services" : ready ? "Review your services" : "Payment Method Required — Add a payment method"}</h3>
          <p>
            ${
              ready
                ? "A payment method is securely saved with Stripe for this client."
                : "Your card will not be charged when you add it. After it is saved, you will review your assigned services and monthly charges before confirming."
            }
          </p>
        </div>
        <div class="hero-stat">
          <span>Status</span>
          <strong>${esc(setupStatusLabel(data.setup_status))}</strong>
          <small>${ready ? esc(cardLabel(data.payment_method)) : "No payment method added"}</small>
        </div>
      </section>

      <div class="grid two">
        ${paymentMethodCard(data)}

        <section class="card">
          <h2>Secure billing</h2>
          <div class="list-item">
            <span class="grow">
              <strong>Saving a card creates no charge</strong>
              <small class="muted">This step only saves a payment method for future authorized billing.</small>
            </span>
          </div>
          <div class="list-item">
            <span class="grow">
              <strong>Card data stays with Stripe</strong>
              <small class="muted">RMR does not store the card number or security code.</small>
            </span>
          </div>
          ${ready ? `<div class="list-item">
            <span class="grow">
              <strong>Monthly services require your approval</strong>
              <small class="muted">Review the server-calculated monthly bill and explicitly authorize activation below.</small>
            </span>
          </div>` : ""}
        </section>
      </div>
      ${monthlyPanel(data)}
    `;

    const consent = $("#billing-monthly-consent");
    const activate = $("#billing-activate-monthly");
    let activating = false;
    consent?.addEventListener("change", () => { if (activate) activate.disabled = activating || !consent.checked; });
    activate?.addEventListener("click", async () => {
      if (!isCurrent() || activating || !consent.checked) return;
      activating = true; activate.disabled = true;
      const box = $("#billing-monthly-result");
      box.textContent = "Activating / Payment Processing...";
      try {
        const result = await runBillingOperation(data.tenant.id, "subscription", "subscription/activate",
          {confirmed:true, quote_hash:data.monthly.quote_hash});
        if (!isCurrent()) return;
        await finishMonthlyPayment(result, data.tenant.id);
        if (!isCurrent()) return;
        await renderBillingPage(ctx);
      } catch (error) { box.textContent = error.message; activating = false; activate.disabled = !consent.checked; }
    });
    const refresh = $("#billing-refresh-monthly");
    refresh?.addEventListener("click", async () => {
      if (!isCurrent() || refresh.disabled) return;
      refresh.disabled = true;
      try {
        const result = await api(`/api/tenants/${data.tenant.id}/billing/subscription/refresh`, {method:"POST"});
        if (!isCurrent()) return;
        await finishMonthlyPayment(result, data.tenant.id);
        if (!isCurrent()) return;
        await renderBillingPage(ctx);
      } catch (error) { $("#billing-monthly-result").textContent = error.message; refresh.disabled = false; }
    });
    const setupButton = $("#billing-add-payment-method");
    setupButton?.addEventListener("click", async () => {
      if (!isCurrent() || setupButton.disabled) return;
      setupButton.disabled = true;
      try { await openPaymentMethodModal(data, ctx, isCurrent); }
      finally { setupButton.disabled = false; }
    });
  } catch (error) {
    if (!isCurrent()) return;
    page.innerHTML = empty("Unable to load Billing & Payments", error.message);
    toast(error.message, "error");
  }
}
