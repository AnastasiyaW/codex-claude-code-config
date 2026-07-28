# Massed Compute provider recipes

Use this reference only when the selected remote-compute adapter is Massed
Compute. Keep the provider session reused and follow the provider-neutral
transport and reconciliation rules in the parent skill.

## Endpoints and configuration

- Documentation: `https://vm-docs.massedcompute.com/docs/category/mcp`
- MCP endpoint: `https://vm.massedcompute.com/api/mcp`
- API-key page: `https://vm.massedcompute.com/settings/api`
- Codex MCP config: `%USERPROFILE%\.codex\config.toml` on Windows or
  `$HOME/.codex/config.toml` on Unix
- Token source: user environment variable `MC_TOKEN`

Ask only for the minimum access needed:

1. A full-access API token copied unchanged from the API-key page when VM
   lifecycle operations are wanted; a read-only token is enough for inventory
   and billing audits.
2. Confirmation that the billing recharge amount and threshold are configured.
3. The SSH public key to register, if the desired key is not already on the
   account. Keep the matching private key local; never upload or paste it.

Account email, account password, website cookies, VM passwords, and payment-card
details are not required.

Configure the MCP server once per task phase:

```toml
[mcp_servers.massed-compute]
url = "https://vm.massedcompute.com/api/mcp"
bearer_token_env_var = "MC_TOKEN"
enabled = true
```

On Windows, persist the token for future processes with:

```powershell
[Environment]::SetEnvironmentVariable('MC_TOKEN', '<token>', 'User')
```

Also set `$env:MC_TOKEN` for the current process when immediate testing is
needed. Restart Codex after changing the persistent value.

## Safe launch recipe

1. Validate token presence and scope.
2. Read billing settings and ensure recharge is configured.
3. List SSH keys; create the named public key only when absent.
4. List live GPU inventory and compatible images.
5. Resolve framework, model size, precision, batch/resolution, GPU count,
   expected duration, region, storage, and budget.
6. Present the selected SKU, image, count, region, hourly/fleet cost, and names.
7. Launch once. If the response is ambiguous, list instances before retrying.
8. Poll by UUID until ready with the bounded polling policy in the parent skill;
   provide SSH coordinates and write the durable run record.

## Training-run recipe

Before starting training, verify that the dataset and base model are already on
durable storage or have a measured transfer path. Record the command/config
path, output/checkpoint path, instance UUID, GPU SKU, hourly cost, start time,
checkpoint cadence, expected stop condition, and recovery command. During a long
run, inspect live process/GPU/log/checkpoint evidence rather than assuming
progress.

## Cost-audit recipe

List instances and live inventory pricing. Report each instance's UUID, name,
GPU, region, state, age, hourly rate, total hourly and daily burn, long-running
or idle-looking instances, recharge settings, and estimated runway. Do not
terminate during an audit; route cleanup through the termination recipe.

## Termination recipe

Resolve filters to exact instances. Show UUID, name, GPU, region, state/uptime,
hourly cost, and any checkpoint/sync risk. Ask for explicit confirmation naming
the targets. Terminate only those UUIDs, then re-list instances and state
whether each target is confirmed absent.

## Official MCP tools

Read-only and full: `gpu_inventory_list`, `images_list`, `instances_list`,
`instances_get`, `coupon_information`, `coupon_accepted_products`,
`account_token_validation`, `account_billing`, `ssh_keys_list`.

Full only: `instances_launch`, `instances_restart`, `instances_terminate`,
`ssh_keys_create`, `ssh_keys_delete`.

Live server extensions observed in July 2026: `recipes_list`, `recipes_search`,
and `recipes_get`. Call `recipes_search` before launching a VM for a known
software setup, then read the matched recipe with `recipes_get`.

## Source documentation

- Overview: `https://vm-docs.massedcompute.com/docs/mcp/overview`
- Client setup: `https://vm-docs.massedcompute.com/docs/mcp/setup`
- Tools: `https://vm-docs.massedcompute.com/docs/mcp/tools`
- Vendor skills: `https://vm-docs.massedcompute.com/docs/mcp/skills`
- Troubleshooting: `https://vm-docs.massedcompute.com/docs/mcp/troubleshooting`
