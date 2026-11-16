# Deploy to AWS (EC2, automatic on every push to `main`)

One EC2 instance runs the same Docker stack as your PC (Redis, API, Celery worker, web) plus
Caddy for HTTPS. GitHub Actions deploys every commit on `main` that passes all checks.

```
push to main ─► CI: lint, tests, Docker smoke test, security scans, deploy rehearsal
                  │ all green
                  ▼
                images ─► GitHub Container Registry (public, free), tag = commit
                  │
                  ▼
                deploy job ─► AWS SSM Run Command ─► EC2: deploy/remote_deploy.sh <commit>
                  │                                    settings from SSM Parameter Store
                  │                                    models from S3 (optional)
                  │                                    swap containers, check /ready,
                  │                                    roll back if the new version fails
                  ▼
                https://<PUBLIC_HOST>/health must report the commit
```

No AWS keys are stored in GitHub (OIDC) and no SSH port is open (SSM).

## What it costs

| Item | Cost |
|---|---|
| Domain + HTTPS | **free**: `<ip-with-dashes>.sslip.io` and a Let's Encrypt certificate (Caddy) |
| Images | **free**: public GitHub Container Registry packages |
| Settings and API keys | **free**: SSM Parameter Store, standard SecureString |
| Deploys | **free**: GitHub Actions (public repo), SSM Run Command, IAM, OIDC |
| Disk 30 GB gp3 | free tier (legacy accounts, first 12 months), otherwise about $3/month |
| Public IPv4 / Elastic IP | 750 h/month free in the first 12 months, otherwise $0.005/hour |
| Models in S3 (~1 GB) | free tier 5 GB, otherwise cents per month. Optional: see step 3 |
| **Server** | the only real cost, see below |

The worker runs PyTorch with three model stages, so it needs **8 GB of RAM**. The free
1 GB instances (`t2.micro`, `t3.micro`) cannot run it.

* **Account created on or after 15 July 2025 (Free plan, $100–200 credits):** use
  `m7i-flex.large` (2 vCPU, 8 GB), which is Free-plan eligible and paid from the credits
  (~$0.12/hour in Sydney, so $200 lasts about 2 months running 24/7, longer if you stop it).
* **Older account (like the one with the signature project):** use `t3.large` (2 vCPU, 8 GB,
  ~$0.106/hour in Sydney, ~$77/month running 24/7).
* Stop the instance when nobody needs it: a stopped instance costs nothing for compute.
  The Elastic IP keeps the address (and the HTTPS name) across stop/start.

Check which you have: AWS console -> **Billing and Cost Management -> Free Tier** (and **Credits**).
Set a budget first (step 0).

---

## Placeholders

| Placeholder | Example | Where it comes from |
|---|---|---|
| `<REGION>` | `ap-southeast-2` | Sydney, same as the signature project |
| `<ACCOUNT_ID>` | `123456789012` | top right of the console (12 digits) |
| `<MODELS_BUCKET>` | `lumber-spine-ai-models-123456789012` | step 3 |
| `<INSTANCE_ID>` | `i-0abc123def4567890` | step 6 |
| `<ELASTIC_IP>` | `13.236.10.20` | step 7 |
| `<PUBLIC_HOST>` | `13-236-10-20.sslip.io` | step 7 (the IP with dashes + `.sslip.io`) |

Select **Asia Pacific (Sydney) ap-southeast-2** in the region menu (top right) before every step.

## 0. Budget alarm (2 minutes)

Billing and Cost Management -> **Budgets** -> Create budget -> *Use a template* ->
**Monthly cost budget** -> amount e.g. `30` USD -> your email -> Create.
You get an email at 85% and 100%, and when the forecast passes it.

## 1. Make the container images public (once)

The images are published by CI to GitHub. The server pulls them without a login, so they
must be public (they contain the code, which is already public; no models, no keys):

GitHub -> your profile -> **Packages** -> for each of `lumber-spine-ai-api`,
`lumber-spine-ai-worker`, `lumber-spine-ai-web-prod`: **Package settings -> Danger Zone ->
Change visibility -> Public**.

`lumber-spine-ai-web-prod` appears after the first CI run on `main` that includes this file.

## 2. Settings and API keys: SSM Parameter Store (free)

Systems Manager -> **Parameter Store** -> Create parameter:

* Name: `/lumber-spine-ai/prod/dotenv`
* Tier: **Standard** (free, up to 4 KB)
* Type: **SecureString**, KMS key: `alias/aws/ssm` (default)
* Value (one setting per line; fill `PUBLIC_HOST` in step 7, `MODELS_S3_URI` in step 3):

```dotenv
PUBLIC_HOST=13-236-10-20.sslip.io
REVIEW_ACCESS_TOKEN=<a long random password for the case library>
REVIEWER_NAME=<your name>
GROQ_API_KEY=<key>
GEMINI_API_KEY=<key>
GROQ_MODELS=qwen/qwen3.8-27b
GEMINI_MODELS=gemini-3.8-flash
LLM_FALLBACK_ORDER=groq,gemini,ollama
LLM_VISION_ORDER=gemini,groq,ollama
LLM_TIMEOUT_SECONDS=90
MODELS_S3_URI=s3://<MODELS_BUCKET>/lumber-spine-ai/model
# Optional, e.g. Ollama on Colab through a tunnel:
# OLLAMA_BASE_URL=https://<tunnel-url>
# OLLAMA_MODELS=qwen3-vl:8b-thinking
```

Rules: no quotes needed, no spaces around `=`, and avoid `$` in values. `REDIS_URL`,
`DATA_DIR`, `MODEL_DIR` and `JOB_BACKEND` are set by `docker-compose.prod.yml`; do not add them.
To change a key later: edit this parameter, then run the workflow again (section 10).

## 3. Model checkpoints: S3 (optional)

The weights are not in Git. The deploy copies them from S3 on every run (only changed files).

S3 -> Create bucket -> name `<MODELS_BUCKET>` (globally unique, e.g. add your account id),
region Sydney, **Block all public access: on** -> Create.
Open the bucket -> Create folder `lumber-spine-ai` -> inside it `model` -> **Upload** every
`.pt` / `.pth` file from your `backend/model` folder.

You can also reuse the signature project's bucket with this folder. Without S3, leave
`MODELS_S3_URI` out and copy the files once to `/home/ubuntu/lumber-spine-ai/backend/model`
on the server (the deploy then uses what is there).

## 4. IAM role for the server

IAM -> Roles -> **Create role** -> Trusted entity: *AWS service*, Use case: **EC2** -> Next.
Permissions: tick **AmazonSSMManagedInstanceCore** -> Next -> Role name
`LumberSpine-EC2-Role` -> Create role.

Open the role -> Add permissions -> **Create inline policy** -> JSON -> paste
[`deploy/iam/ec2-role-policy.json`](../deploy/iam/ec2-role-policy.json) with `<REGION>`,
`<ACCOUNT_ID>` and `<MODELS_BUCKET>` replaced (delete the two S3 statements if you skip S3)
-> name `lumber-spine-ai-runtime` -> Create.

## 5. Security group

EC2 -> Security Groups -> **Create security group** -> name `lumber-spine-ai-web`, default VPC.
Inbound rules:

| Type | Port | Source |
|---|---|---|
| HTTP | 80 | Anywhere-IPv4 (needed for the Let's Encrypt certificate) |
| HTTPS | 443 | Anywhere-IPv4 |

No SSH rule: you reach the server with Session Manager. Outbound: leave "all traffic".

## 6. Launch the instance

EC2 -> **Launch instance**:

* Name: `lumber-spine-ai`
* AMI: **Ubuntu Server 24.04 LTS**, architecture **64-bit (x86)** (the images are x86)
* Instance type: `m7i-flex.large` (Free-plan accounts) or `t3.large` (other accounts)
* Key pair: **Proceed without a key pair**
* Network settings -> Edit: auto-assign public IP **Enable**, security group
  `lumber-spine-ai-web`
* Storage: **30 GiB gp3**
* Advanced details: IAM instance profile **LumberSpine-EC2-Role**; Metadata version
  **V2 only**; **User data**: paste all of [`deploy/ec2_user_data.sh`](../deploy/ec2_user_data.sh)
* Launch instance. Copy the **Instance ID** (`<INSTANCE_ID>`).

The user data installs Docker, the AWS CLI and 4 GB swap, and clones the repository
(about 5 minutes).

## 7. Elastic IP and the free domain

EC2 -> **Elastic IPs** -> Allocate -> Allocate. Select it -> Actions -> **Associate** ->
instance `lumber-spine-ai` -> Associate. This is `<ELASTIC_IP>`.

Your free domain is the IP with dashes plus `.sslip.io`, e.g. `13.236.10.20` ->
**`13-236-10-20.sslip.io`**. It resolves to your IP with no sign-up, and Caddy gets a
Let's Encrypt certificate for it. Put it in the parameter of step 2 (`PUBLIC_HOST=`).

Optional nicer name, also free: <https://www.duckdns.org> -> sign in -> add e.g.
`lumberspine` -> current ip `<ELASTIC_IP>` -> use `lumberspine.duckdns.org` as `PUBLIC_HOST`
(in step 2 and step 9). A domain you buy works the same way with an A record to `<ELASTIC_IP>`.

## 8. Check the server

Systems Manager -> **Fleet Manager**: the instance should be **Online** (5–10 minutes after
launch). Then EC2 -> select it -> **Connect** -> *Session Manager* -> Connect:

```bash
sudo tail -n 5 /var/log/cloud-init-output.log   # ends with: SERVER READY ...
docker --version && aws --version
```

## 9. Let GitHub deploy (OIDC, no keys)

**Identity provider** (once per AWS account; skip if it exists): IAM -> Identity providers ->
Add provider -> **OpenID Connect** -> Provider URL `https://token.actions.githubusercontent.com`,
Audience `sts.amazonaws.com` -> Add provider.

**Deploy role:** IAM -> Roles -> Create role -> **Web identity** -> Identity provider
`token.actions.githubusercontent.com`, Audience `sts.amazonaws.com`, GitHub organization
`abduIIahKhaIid`, repository `Lumber-Spine-AI` -> Next -> no permissions -> Next ->
name `LumberSpine-GitHub-Deploy` -> Create role. Then:

* Trust relationships -> **Edit trust policy** -> paste
  [`deploy/iam/github-trust-policy.json`](../deploy/iam/github-trust-policy.json) with
  `<ACCOUNT_ID>` replaced -> Update. (It allows only the `production` environment of this
  repository.) This repository was created after GitHub switched new repositories to
  immutable OIDC subjects. Its subject includes the public owner ID `91344658` and repository
  ID `1459133201`; do not remove those IDs from the policy. The policy also accepts the
  older name-only subject, so it keeps working whichever form GitHub sends.
* Add permissions -> Create inline policy -> JSON -> paste
  [`deploy/iam/github-deploy-policy.json`](../deploy/iam/github-deploy-policy.json) with
  `<REGION>`, `<ACCOUNT_ID>`, `<INSTANCE_ID>` replaced -> name `lumber-spine-ai-deploy`.
  (It can only run commands on this one instance.)
* Copy the role **ARN**.

**If OIDC is not available in your account** (some Free-plan accounts cannot create the
identity provider), use an IAM user with the same narrow permission instead:
IAM -> Users -> Create user `lumber-spine-ai-deploy` (no console access) -> Attach policies
directly -> skip -> Create user. Open it -> Add permissions -> Create inline policy -> JSON ->
paste `deploy/iam/github-deploy-policy.json` (placeholders replaced) -> name
`lumber-spine-ai-deploy`. Then Security credentials -> **Create access key** -> *Application
running outside AWS* -> copy both values. In GitHub add them as repository **secrets**
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` and leave out the `AWS_ROLE_ARN` variable.
The keys can only start the deploy on this one instance. Rotate them if they ever leak.

**GitHub:** repository -> Settings -> **Environments** -> New environment `production` ->
Configure (no reviewers: deploys are automatic). Restrict deployment branches to `main`.
Then Settings -> **Secrets and variables ->
Actions -> Variables** tab -> New repository variable, four times:

| Name | Value |
|---|---|
| `AWS_ROLE_ARN` | `arn:aws:iam::<ACCOUNT_ID>:role/LumberSpine-GitHub-Deploy` (not with the IAM user keys) |
| `AWS_REGION` | `ap-southeast-2` |
| `EC2_INSTANCE_ID` | `<INSTANCE_ID>` |
| `PUBLIC_HOST` | `<PUBLIC_HOST>` |

With OIDC no GitHub secrets are needed.

## 10. First deploy, and every deploy after it

Actions -> **CI** -> *Run workflow* -> branch `main` -> Run. The first run takes about
20–30 minutes (all checks, image builds, first image pull on the server). Then open
`https://<PUBLIC_HOST>`.

From now on every push to `main` deploys by itself after all checks pass. The run summary
shows "Deployed <commit> to https://...". If the new version fails its checks on the server,
the previous version is started again and the job turns red with `ROLLED_BACK` in its log.

Run the workflow by hand after changing the parameter (step 2) or the models (step 3).

## Daily operations (Session Manager)

```bash
cd /home/ubuntu/lumber-spine-ai
C="sudo docker compose -f docker-compose.prod.yml --env-file deploy/runtime.env"
$C ps                       # containers and health
$C logs -f --tail 100 api   # or worker, web, caddy
cat deploy/.deployed_sha    # commit that is live
sudo bash deploy/remote_deploy.sh <commit>   # deploy or roll back to any published commit
```

* Backups: EC2 -> Lifecycle Manager -> create a daily EBS snapshot policy for the instance
  (saved cases and conversations live in the Docker volume on that disk).
* Stop / start: EC2 -> Instance state. Containers start again on boot by themselves.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy job: *Not authorized to perform sts:AssumeRoleWithWebIdentity* | trust policy: account id, repository `abduIIahKhaIid/Lumber-Spine-AI`, environment `production` |
| *InvalidInstanceId* from SSM | the instance is not Online in Fleet Manager: role `LumberSpine-EC2-Role` with `AmazonSSMManagedInstanceCore`, instance running |
| `cannot pull ghcr.io/...` | step 1: the packages must be public |
| `the parameter is missing: ...` | add the key to `/lumber-spine-ai/prod/dotenv` (step 2) |
| `could not download the models` | `MODELS_S3_URI`, bucket name and the S3 statements of the server role |
| `not ready after 360 s` | worker log: missing model files or out of memory (use an 8 GB instance) |
| Browser: certificate error | ports 80 and 443 open (step 5); `PUBLIC_HOST` matches the Elastic IP; `$C logs caddy` |
| Deploy skipped (green) | the four repository variables of step 9 are not all set |
