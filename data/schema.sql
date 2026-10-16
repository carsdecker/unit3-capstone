-- Consulting-firm schema (course file schema-query.sql, unchanged).

CREATE TABLE clients (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    region TEXT,
    contract_value NUMERIC,
    created_date DATE
);

CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id),
    name TEXT NOT NULL,
    status TEXT,
    start_date DATE,
    end_date DATE,
    budget NUMERIC
);

CREATE TABLE consultants (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    grade TEXT,
    specialisation TEXT,
    project_id INTEGER REFERENCES projects(id),
    billable_hours NUMERIC
);

CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    amount NUMERIC,
    status TEXT,
    due_date DATE,
    paid_date DATE
);

INSERT INTO clients (name, industry, region, contract_value, created_date) VALUES
('Acme Corp', 'Retail', 'North', 250000, '2025-01-15'),
('Beta Financial', 'Finance', 'East', 480000, '2025-03-01'),
('Gamma Health', 'Healthcare', 'South', 320000, '2025-02-10'),
('Delta Manufacturing', 'Manufacturing', 'West', 190000, '2025-04-05'),
('Epsilon Retail', 'Retail', 'North', 275000, '2025-05-20');

INSERT INTO projects (client_id, name, status, start_date, end_date, budget) VALUES
(1, 'Client Portal Redesign', 'active', '2025-02-01', NULL, 150000),
(1, 'Data Migration', 'completed', '2025-01-20', '2025-03-15', 90000),
(2, 'Fraud Detection System', 'active', '2025-03-10', NULL, 220000),
(3, 'Patient Records Modernization', 'on-hold', '2025-02-15', NULL, 180000),
(4, 'Supply Chain Analytics', 'active', '2025-04-10', NULL, 130000),
(5, 'Inventory Management Overhaul', 'active', '2025-05-25', NULL, 160000);

INSERT INTO consultants (name, grade, specialisation, project_id, billable_hours) VALUES
('Alice Chen', 'Senior', 'Frontend Engineering', 1, 320),
('Bob Martinez', 'Manager', 'Data Engineering', 2, 210),
('Carol White', 'Analyst', 'Data Science', 3, 180),
('Dana Okafor', 'Senior', 'Healthcare Systems', 4, 95),
('Evan Park', 'Manager', 'Analytics', 5, 240),
('Fiona Reyes', 'Director', 'Strategy', 6, 150);

INSERT INTO invoices (project_id, amount, status, due_date, paid_date) VALUES
(1, 45000, 'paid', '2025-03-01', '2025-02-28'),
(1, 45000, 'pending', '2025-05-01', NULL),
(2, 90000, 'paid', '2025-03-20', '2025-03-18'),
(3, 55000, 'overdue', '2025-04-01', NULL),
(4, 45000, 'pending', '2025-05-15', NULL),
(5, 32500, 'paid', '2025-05-01', '2025-04-29'),
(6, 58000, 'pending', '2025-06-01', NULL);