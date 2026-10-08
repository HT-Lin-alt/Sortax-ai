# ATO Demo source manifest

The Demo scope is fixed to tax year **2025–26** and these claim types:

- `salary_wages`
- `working_from_home`
- `self_education`
- `work_related_car`
- `residential_rental_property`
- `australian_bank_interest`

HTML and PDF are both in scope. Automated tests and local development use the
deterministic `FakeEmbeddingProvider` by default; a real provider is opt-in.

The project maintainer must manually open each `source_url` in `sources.yaml`,
save the content at the corresponding `local_path`, and review that the saved
document applies to the declared tax year before ingestion. The title in the
manifest must describe the saved document rather than the local filename. The
application does not download, refresh, or authenticate ATO content. Missing
local files are expected until that manual preparation step is complete.

After saving the reviewed files, run a non-writing validation first:

```powershell
python -m sortax.knowledge.ingest --manifest manifests/ato/sources.yaml --dry-run
```

Then run the same command without `--dry-run` to create embeddings and write the
`ato_knowledge_demo` collection. Re-running unchanged files skips them by content
hash. Use `--rebuild` only for an intentional full collection replacement.

`demo-questions.yaml` contains eight acceptance prompts. A grounded result must
cite at least one imported source with the same `claim_type` and tax year. The
clarification and insufficient-evidence cases must not produce an ATO checklist.
