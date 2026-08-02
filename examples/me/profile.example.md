# Jordan Rivers — Professional Profile

<!--
Fully fictional example profile that ships with the public toolkit. "Jordan
Rivers" is a made-up mid/senior software engineer; the employer, school,
projects, and metrics below are all invented to demonstrate the resume-writer
schema. Replace this file (via your own config.yaml) with your real profile.
-->

## Contact

- Location: City, ST
- Email: jordan.rivers@example.com
- LinkedIn: linkedin.com/in/jordanrivers

## Career Summary

- Senior software engineer with 8+ years building scalable backend services and distributed systems in production
- Specialize in cloud-native microservices on AWS and Kubernetes, with a focus on reliability, performance, and cost
- Partner closely with product and SRE teams to ship well-tested APIs, automation, and observability at scale

## Role Description (don't include in resume)

Senior software engineer with 8+ years of experience, focused on backend and platform engineering, bringing depth in distributed systems, cloud infrastructure, API design, and building the automation and observability that let product teams ship quickly and safely.

## Education

B.S. in Computer Science, Lakemont University, 2015

## Skills

### Approved (include in most resumes, if not all)

- Programming Languages: Python, Java, Go, JavaScript, TypeScript, SQL, Bash, HTML, CSS
- Skills: AWS, EC2, S3, Docker, Kubernetes, Terraform, PostgreSQL, Redis, gRPC, REST APIs, GraphQL, microservices, distributed systems, event-driven architecture, message queues, caching, CI/CD, Git, observability, React, Node.js

### Weak (user-facing: Weak or Selective — include ONLY when the JD specifically mentions it)

- Cloud & Infra: AWS (Lambda, SQS, SNS), Kafka, RabbitMQ, service mesh
- Frontend: Vue, Next.js, Angular
- Data & Search: Elasticsearch, MongoDB, DynamoDB, data pipelines
- CI/CD & Collaboration: GitHub Actions, Jenkins, Jira, Confluence

### Never (never include in any resume)

- Languages: Rust, C++, C#, Scala, Ruby, Kotlin, Elixir
- Cloud: GCP, Azure, Vertex AI, multi-cloud
- Data & big data: Hadoop, Spark, Flink, Snowflake, Databricks
- AI/ML: PyTorch, TensorFlow, JAX, LangChain, model serving, vector databases
- Infra: Istio, Envoy, Consul, Ansible, Puppet, Chef
- Other: COBOL, Salesforce, SAP, mainframe

## Experience

### Northwind Systems — Senior Software Engineer (2016 – Present, City, ST)

#### [draft] Payments platform microservices migration

- Led migration of a monolithic payments service into independently deployable microservices, cutting deploy time from hours to minutes
- Designed idempotent transaction workflows and retry semantics that reduced failed-payment incidents by 40%
- Introduced contract tests and canary releases so teams could ship changes safely without cross-team coordination

#### [draft] Real-time notifications and event pipeline

- Built an event-driven notifications pipeline processing 50M+ daily events with at-least-once delivery guarantees
- Implemented backpressure and dead-letter queues to keep the system stable during downstream outages and traffic spikes
- Cut end-to-end notification latency from minutes to under two seconds at the 99th percentile

#### [draft] Public REST and gRPC API gateway

- Designed and shipped a public API gateway exposing REST and gRPC endpoints to thousands of third-party developers
- Added authentication, rate limiting, and request validation as reusable middleware shared across services
- Authored versioned API docs and client SDKs that reduced partner integration time from weeks to days

#### [draft] Observability and incident response tooling

- Rolled out structured logging, metrics, and distributed tracing across 30+ services for end-to-end visibility
- Built on-call dashboards and automated runbooks that cut mean time to resolution by roughly 35%
- Established service-level objectives and alerting policies adopted as the team standard for new services

#### [draft] Customer onboarding automation service

- Automated customer onboarding workflows with a self-service portal, replacing manual, error-prone provisioning
- Cut new-customer setup time from days to under an hour and removed a recurring class of provisioning errors
- Partnered with support and product teams to define self-serve usage tiers and limits for new tenants

#### [backup] Search relevance and indexing service

- Rebuilt the product search backend on an inverted-index service, improving relevance and cutting query latency by half
- Designed incremental indexing so catalog updates appeared in search results within seconds instead of hours
- Added A/B testing hooks that let product managers safely experiment with ranking changes in production

#### [backup] CI/CD pipeline modernization

- Migrated the team from ad-hoc scripts to a containerized CI/CD pipeline with automated testing and staged rollouts
- Reduced average build-and-deploy time by 60% and eliminated most manual release steps
- Standardized infrastructure-as-code with Terraform so environments could be recreated on demand

---

## Resume Writing Preferences

- **Format**: 3 sections — Summary, Education & Skills, Experience
- **Summary style**: 3 bullet-point statements (bold), not a paragraph
- **Education & Skills**: Combined into a single section. Education on the first line, then Programming Languages, then Skills
- **Experience layout**: Project-based under a single employer, not a list of companies. Employer header on one line, then project blocks with a bold title + bullet points
- **Project selection**: Use [draft] projects by default (pick ~5 that best fit the JD). Use [backup] projects only if they are a significantly better fit than one of the draft projects for the specific role
- **Skills selection**: Three stored lists in the Skills section — Approved (include in most resumes, if not all), Weak (shown to users as Weak or Selective; include only when the JD specifically mentions it), and Never (never include in any resume). Any JD skill not in the three lists must be surfaced at the end of a tailoring run so it can be categorized
- **Rewording**: Allowed and encouraged to reword bullets to better match JD keywords, but the underlying experience must be real
- **Guardrails**: No false information. No fabricated metrics. No technologies I haven't used. No inflated job titles
- **Length**: One page. Roughly 5 projects with 2-3 bullets each
- **Section headers**: Use exactly "Summary", "Education & Skills", "Experience" — no creative alternatives
- **Bullet style**: Start with strong action verbs. Quantify impact where possible. Mirror JD terminology where honest
