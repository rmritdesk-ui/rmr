CREATE TABLE schema_migrations (
	version VARCHAR(64) NOT NULL, 
	applied_at DATETIME NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE service_catalog (
	id VARCHAR(36) NOT NULL, 
	code VARCHAR(80) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	standard_price_cents INTEGER NOT NULL, 
	cadence VARCHAR(30) NOT NULL, 
	unit VARCHAR(50) NOT NULL, 
	direct_cost_cents INTEGER NOT NULL, 
	split_basis VARCHAR(20) NOT NULL, 
	rmr_share_pct FLOAT NOT NULL, 
	step2_share_pct FLOAT NOT NULL, 
	active BOOLEAN NOT NULL, 
	sort_order INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_service_catalog_code ON service_catalog (code);

CREATE TABLE tenants (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	industry VARCHAR(120) NOT NULL, 
	country VARCHAR(80) NOT NULL, 
	timezone VARCHAR(80) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	seller_org VARCHAR(40) NOT NULL, 
	seller_name VARCHAR(160) NOT NULL, 
	onboarding_owner VARCHAR(80) NOT NULL, 
	website_mode VARCHAR(40) NOT NULL, 
	website_url VARCHAR(500) NOT NULL, 
	managed_site_slug VARCHAR(120) NOT NULL, 
	adoption_score INTEGER NOT NULL, 
	training_completion_pct INTEGER NOT NULL, 
	health_status VARCHAR(40) NOT NULL, 
	renewal_risk VARCHAR(40) NOT NULL, 
	primary_contact_name VARCHAR(160) NOT NULL, 
	primary_contact_email VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_tenants_status ON tenants (status);

CREATE UNIQUE INDEX ix_tenants_slug ON tenants (slug);

CREATE TABLE economic_transactions (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	service_code VARCHAR(80) NOT NULL, 
	period VARCHAR(20) NOT NULL, 
	quantity FLOAT NOT NULL, 
	unit_price_cents INTEGER NOT NULL, 
	revenue_cents INTEGER NOT NULL, 
	direct_cost_cents INTEGER NOT NULL, 
	split_basis VARCHAR(20) NOT NULL, 
	rmr_share_pct FLOAT NOT NULL, 
	step2_share_pct FLOAT NOT NULL, 
	rmr_share_cents INTEGER NOT NULL, 
	step2_share_cents INTEGER NOT NULL, 
	invoice_reference VARCHAR(120) NOT NULL, 
	trace_reference VARCHAR(120) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	UNIQUE (trace_reference)
);

CREATE INDEX ix_economic_transactions_period ON economic_transactions (period);

CREATE INDEX ix_economic_transactions_service_code ON economic_transactions (service_code);

CREATE INDEX ix_economic_transactions_tenant_id ON economic_transactions (tenant_id);

CREATE TABLE notifications (
	id VARCHAR(36) NOT NULL, 
	recipient_scope VARCHAR(80) NOT NULL, 
	tenant_id VARCHAR(36), 
	notification_type VARCHAR(80) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	body TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_notifications_recipient_scope ON notifications (recipient_scope);

CREATE INDEX ix_notifications_status ON notifications (status);

CREATE TABLE onboarding_projects (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	current_stage INTEGER NOT NULL, 
	readiness_pct INTEGER NOT NULL, 
	target_go_live DATE, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_onboarding_projects_tenant_id ON onboarding_projects (tenant_id);

CREATE TABLE piq_opportunities (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	company_name VARCHAR(200) NOT NULL, 
	score INTEGER NOT NULL, 
	signal VARCHAR(300) NOT NULL, 
	evidence_count INTEGER NOT NULL, 
	estimated_value_cents INTEGER NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	enhanced BOOLEAN NOT NULL, 
	enhancement_price_cents INTEGER NOT NULL, 
	moved_to_crm BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_piq_opportunities_tenant_id ON piq_opportunities (tenant_id);

CREATE TABLE tenant_services (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	service_code VARCHAR(80) NOT NULL, 
	contract_price_cents INTEGER NOT NULL, 
	usage_price_cents INTEGER NOT NULL, 
	cadence VARCHAR(30) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	effective_date DATE NOT NULL, 
	next_billing_date DATE, 
	quantity FLOAT NOT NULL, 
	notes TEXT NOT NULL, 
	source_request_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tenant_service UNIQUE (tenant_id, service_code), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(service_code) REFERENCES service_catalog (code)
);

CREATE INDEX ix_tenant_services_service_code ON tenant_services (service_code);

CREATE INDEX ix_tenant_services_tenant_id ON tenant_services (tenant_id);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(500) NOT NULL, 
	full_name VARCHAR(160) NOT NULL, 
	global_role VARCHAR(50), 
	tenant_id VARCHAR(36), 
	tenant_role VARCHAR(50), 
	manager_id VARCHAR(36), 
	team_name VARCHAR(120) NOT NULL, 
	active BOOLEAN NOT NULL, 
	must_change_password BOOLEAN NOT NULL, 
	last_login_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(manager_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE INDEX ix_users_global_role ON users (global_role);

CREATE INDEX ix_users_tenant_id ON users (tenant_id);

CREATE INDEX ix_users_tenant_role ON users (tenant_role);

CREATE TABLE website_sites (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	mode VARCHAR(40) NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	template_family VARCHAR(80) NOT NULL, 
	company_name VARCHAR(200) NOT NULL, 
	wordmark VARCHAR(160) NOT NULL, 
	primary_color VARCHAR(20) NOT NULL, 
	secondary_color VARCHAR(20) NOT NULL, 
	accent_color VARCHAR(20) NOT NULL, 
	heading_font VARCHAR(80) NOT NULL, 
	body_font VARCHAR(80) NOT NULL, 
	button_style VARCHAR(40) NOT NULL, 
	nav_style VARCHAR(40) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	external_url VARCHAR(500) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_website_sites_slug ON website_sites (slug);

CREATE UNIQUE INDEX ix_website_sites_tenant_id ON website_sites (tenant_id);

CREATE TABLE accounts (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	owner_user_id VARCHAR(36), 
	team_name VARCHAR(120) NOT NULL, 
	annual_value_cents INTEGER NOT NULL, 
	source VARCHAR(80) NOT NULL, 
	risk VARCHAR(40) NOT NULL, 
	notes TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_accounts_name ON accounts (name);

CREATE INDEX ix_accounts_tenant_id ON accounts (tenant_id);

CREATE TABLE audit_events (
	id VARCHAR(36) NOT NULL, 
	actor_user_id VARCHAR(36), 
	tenant_id VARCHAR(36), 
	event_type VARCHAR(120) NOT NULL, 
	entity_type VARCHAR(80) NOT NULL, 
	entity_id VARCHAR(80) NOT NULL, 
	event_data JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_audit_events_event_type ON audit_events (event_type);

CREATE INDEX ix_audit_events_tenant_id ON audit_events (tenant_id);

CREATE INDEX ix_audit_events_actor_user_id ON audit_events (actor_user_id);

CREATE TABLE campaigns (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	channel VARCHAR(80) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	content TEXT NOT NULL, 
	scheduled_at DATETIME, 
	approved_by VARCHAR(36), 
	created_by VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(approved_by) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_campaigns_tenant_id ON campaigns (tenant_id);

CREATE TABLE forecast_versions (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	fiscal_year INTEGER NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	annual_goal_cents INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_by VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_forecast_versions_tenant_id ON forecast_versions (tenant_id);

CREATE TABLE leads (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	company_name VARCHAR(200) NOT NULL, 
	contact_name VARCHAR(160) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	phone VARCHAR(80) NOT NULL, 
	source VARCHAR(80) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	notes TEXT NOT NULL, 
	assigned_user_id VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(assigned_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_leads_tenant_id ON leads (tenant_id);

CREATE TABLE onboarding_steps (
	id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36) NOT NULL, 
	stage_number INTEGER NOT NULL, 
	code VARCHAR(80) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	owner_role VARCHAR(100) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	data_json JSON NOT NULL, 
	notes TEXT NOT NULL, 
	completed_by VARCHAR(160) NOT NULL, 
	completed_at DATETIME, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_onboarding_stage UNIQUE (project_id, stage_number), 
	FOREIGN KEY(project_id) REFERENCES onboarding_projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_onboarding_steps_project_id ON onboarding_steps (project_id);

CREATE TABLE solution_interest (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	service_code VARCHAR(80) NOT NULL, 
	event_type VARCHAR(50) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_solution_interest_created_at ON solution_interest (created_at);

CREATE INDEX ix_solution_interest_service_code ON solution_interest (service_code);

CREATE INDEX ix_solution_interest_tenant_id ON solution_interest (tenant_id);

CREATE TABLE solution_requests (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	service_code VARCHAR(80) NOT NULL, 
	requested_by VARCHAR(36) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	note TEXT NOT NULL, 
	proposed_monthly_cents INTEGER NOT NULL, 
	proposed_usage_cents INTEGER NOT NULL, 
	preferred_contact_method VARCHAR(40) NOT NULL, 
	best_time VARCHAR(120) NOT NULL, 
	reviewed_by VARCHAR(36), 
	reviewed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(requested_by) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(reviewed_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_solution_requests_status ON solution_requests (status);

CREATE INDEX ix_solution_requests_service_code ON solution_requests (service_code);

CREATE INDEX ix_solution_requests_tenant_id ON solution_requests (tenant_id);

CREATE TABLE support_access (
	id VARCHAR(36) NOT NULL, 
	admin_user_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	area VARCHAR(120) NOT NULL, 
	purpose VARCHAR(300) NOT NULL, 
	access_type VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(admin_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_support_access_admin_user_id ON support_access (admin_user_id);

CREATE INDEX ix_support_access_tenant_id ON support_access (tenant_id);

CREATE TABLE training_resources (
	id VARCHAR(36) NOT NULL, 
	title VARCHAR(220) NOT NULL, 
	description TEXT NOT NULL, 
	module VARCHAR(100) NOT NULL, 
	media_type VARCHAR(30) NOT NULL, 
	media_url VARCHAR(1000) NOT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	required BOOLEAN NOT NULL, 
	roles_json JSON NOT NULL, 
	product_version VARCHAR(40) NOT NULL, 
	duration_minutes INTEGER NOT NULL, 
	published BOOLEAN NOT NULL, 
	created_by VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE website_pages (
	id VARCHAR(36) NOT NULL, 
	site_id VARCHAR(36) NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	nav_order INTEGER NOT NULL, 
	show_in_nav BOOLEAN NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	seo_title VARCHAR(200) NOT NULL, 
	seo_description VARCHAR(400) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_site_page_slug UNIQUE (site_id, slug), 
	FOREIGN KEY(site_id) REFERENCES website_sites (id) ON DELETE CASCADE
);

CREATE INDEX ix_website_pages_site_id ON website_pages (site_id);

CREATE TABLE contacts (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	account_id VARCHAR(36), 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100) NOT NULL, 
	title VARCHAR(140) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	phone VARCHAR(80) NOT NULL, 
	primary_contact BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE
);

CREATE INDEX ix_contacts_account_id ON contacts (account_id);

CREATE INDEX ix_contacts_tenant_id ON contacts (tenant_id);

CREATE TABLE forecast_months (
	id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	account_id VARCHAR(36) NOT NULL, 
	month INTEGER NOT NULL, 
	prior_actual_cents INTEGER NOT NULL, 
	forecast_cents INTEGER NOT NULL, 
	actual_cents INTEGER NOT NULL, 
	growth_pct FLOAT NOT NULL, 
	notes TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_forecast_account_month UNIQUE (version_id, account_id, month), 
	FOREIGN KEY(version_id) REFERENCES forecast_versions (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE
);

CREATE INDEX ix_forecast_months_account_id ON forecast_months (account_id);

CREATE INDEX ix_forecast_months_version_id ON forecast_months (version_id);

CREATE TABLE training_progress (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	resource_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	progress_pct INTEGER NOT NULL, 
	completed_at DATETIME, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_training_progress UNIQUE (tenant_id, user_id, resource_id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(resource_id) REFERENCES training_resources (id) ON DELETE CASCADE
);

CREATE INDEX ix_training_progress_resource_id ON training_progress (resource_id);

CREATE INDEX ix_training_progress_user_id ON training_progress (user_id);

CREATE INDEX ix_training_progress_tenant_id ON training_progress (tenant_id);

CREATE TABLE website_sections (
	id VARCHAR(36) NOT NULL, 
	page_id VARCHAR(36) NOT NULL, 
	section_type VARCHAR(80) NOT NULL, 
	position INTEGER NOT NULL, 
	visible BOOLEAN NOT NULL, 
	settings_json JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(page_id) REFERENCES website_pages (id) ON DELETE CASCADE
);

CREATE INDEX ix_website_sections_page_id ON website_sections (page_id);

CREATE TABLE opportunities (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	account_id VARCHAR(36), 
	contact_id VARCHAR(36), 
	owner_user_id VARCHAR(36), 
	name VARCHAR(200) NOT NULL, 
	stage VARCHAR(60) NOT NULL, 
	value_cents INTEGER NOT NULL, 
	probability_pct INTEGER NOT NULL, 
	expected_close_date DATE, 
	source VARCHAR(80) NOT NULL, 
	next_action VARCHAR(300) NOT NULL, 
	loss_reason VARCHAR(300) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
	FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
	FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_opportunities_tenant_id ON opportunities (tenant_id);

CREATE TABLE activities (
	id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(36) NOT NULL, 
	account_id VARCHAR(36), 
	opportunity_id VARCHAR(36), 
	user_id VARCHAR(36), 
	activity_type VARCHAR(40) NOT NULL, 
	subject VARCHAR(200) NOT NULL, 
	body TEXT NOT NULL, 
	due_at DATETIME, 
	completed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE SET NULL, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_activities_tenant_id ON activities (tenant_id);
