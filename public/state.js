export const state = {
  user: null,
  tenants: [],
  selectedTenantId: null,
  tenantTheme: null,
  route: '',
  routeQuery: {},
  routeHistory: [],
  modules: [],
  moduleServices: [],
  adminClientWorkspace: false,
  managedSession: null,
  unifiedTab: {},
  crmTab: 'accounts',
  selectedWebsitePageId: null,
  selectedWebsiteSectionId: null,
  glossary: {
    MRR: 'Monthly Recurring Revenue — contracted recurring revenue expected each month.',
    ARR: 'Annual Recurring Revenue — monthly recurring revenue annualized over 12 months.',
    CRM: 'Customer Relationship Management — accounts, contacts, leads, opportunities and activities.',
    PIQ: 'ProspectIQ — RMR opportunity intelligence and paid profile enhancement capability.',
    TTM: 'Trailing Twelve Months — the most recent 12-month period ending with the selected month.',
    MTD: 'Month to Date — results from the beginning of the current month through today.',
    QTD: 'Quarter to Date — results from the beginning of the current quarter through today.',
    YTD: 'Year to Date — results from the beginning of the fiscal year through today.',
    SEO: 'Search Engine Optimization — improving website visibility in search results.',
    ROI: 'Return on Investment — value or return compared with cost.',
    KPI: 'Key Performance Indicator — a measure used to monitor performance.',
    API: 'Application Programming Interface — a controlled way for systems to exchange data.',
    MFA: 'Multi-Factor Authentication — more than one verification factor during sign-in.',
    OAuth: 'A delegated authorization method used to connect external services without sharing passwords.',
    CSV: 'Comma-Separated Values — a common spreadsheet-compatible import and export format.',
    RBAC: 'Role-Based Access Control — permissions based on a user’s assigned role.',
    SSL: 'Secure Sockets Layer — commonly used to describe encrypted HTTPS website connections.',
    DNS: 'Domain Name System — connects a domain name to its server destination.'
  }
};

export function isGlobalAdmin() {
  return ['RMR_OWNER', 'STEP2_ADMIN'].includes(state.user?.global_role);
}

export function selectedTenant() {
  return state.tenants.find(t => t.id === state.selectedTenantId) || null;
}
