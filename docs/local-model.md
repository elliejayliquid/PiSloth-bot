# Local model bring-up

This is a manual benchmark gate, not an autonomous boot service. Keep PiSloth
powered off until the operator is ready, and do not enable physical motion while
testing the planner.

## Baseline

Start with Gemma 3 270M IT Q8_0. It is small enough to establish real latency
and memory numbers on the 4 GB Raspberry Pi before considering Gemma 3 1B.

Pinned artifacts:

- llama.cpp `b10786`, Ubuntu arm64 CPU archive;
- `gemma-3-270m-it-Q8_0.gguf` at model commit `795e608`;
- model size: 291,545,600 bytes (about 278 MiB / 292 MB).

The two downloads total about 305 MB. Allow roughly 400 MB of disk space for
downloads plus extracted binaries. Runtime RAM must be measured on the Pi; a
reasonable preflight allowance is 0.5-1 GB. There is no API cost because
inference remains local.

Gemma is subject to its published terms. Review them before downloading:
https://ai.google.dev/gemma/terms

## One resumable download and install command

Run this on PiSloth only after explicit approval. It does not create a service,
open a LAN port, or run the model.

```bash
set -euo pipefail
install -d -m 0755 "$HOME/downloads" "$HOME/opt/llama-b10786" "$HOME/models"
cd "$HOME/downloads"
curl --fail --location --continue-at - --output llama-b10786-bin-ubuntu-arm64.tar.gz https://github.com/ggml-org/llama.cpp/releases/download/b10786/llama-b10786-bin-ubuntu-arm64.tar.gz
printf '%s  %s\n' b6992277b7c2b2804957434edd9f775e20c1bdd7065e1299d6187c766074dfa2 llama-b10786-bin-ubuntu-arm64.tar.gz | sha256sum --check -
tar --extract --gzip --file llama-b10786-bin-ubuntu-arm64.tar.gz --directory "$HOME/opt/llama-b10786"
curl --fail --location --continue-at - --output "$HOME/models/gemma-3-270m-it-Q8_0.gguf" 'https://huggingface.co/ggml-org/gemma-3-270m-it-GGUF/resolve/795e608e4e6c8cba79de3feba50364bf3b6d51c2/gemma-3-270m-it-Q8_0.gguf?download=true'
printf '%s  %s\n' 0ef57d2c838458a1952664260dcba38e5bdda37494f3af732f06e4add24068e3 "$HOME/models/gemma-3-270m-it-Q8_0.gguf" | sha256sum --check -
```

If the network drops, run the same block again. `curl --continue-at -` resumes
partial files, and both artifacts are checked before use.

## Manual server and evaluation

From one SSH session, locate the extracted binary and start a loopback-only,
single-slot server:

```bash
server_bin="$(find "$HOME/opt/llama-b10786" -type f -name llama-server -print -quit)"
test -n "$server_bin"
server_dir="$(dirname "$server_bin")"
LD_LIBRARY_PATH="$server_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$server_bin" \
  --model "$HOME/models/gemma-3-270m-it-Q8_0.gguf" \
  --alias ggml-org/gemma-3-270m-it-GGUF:Q8_0 \
  --host 127.0.0.1 --port 8080 \
  --threads 4 --parallel 1 --ctx-size 2048 --no-webui
```

In a second SSH session:

```bash
cd /home/pi/pisloth-brain
. .venv/bin/activate
PYTHONPATH=src python -m pisloth_brain planner-eval
```

The gate passes only if all cases pass without fallback. Record the reported
average model latency and separately inspect server RSS with
`ps -o pid,rss,etime,cmd -C llama-server`. Stop the server with `Ctrl+C` after
the test. Do not configure systemd or autonomous movement at this stage.

## Sources

- Gemma setup and model sizing: https://ai.google.dev/gemma/docs/get_started
- Quantized model artifact and checksum: https://huggingface.co/ggml-org/gemma-3-270m-it-GGUF/blob/main/gemma-3-270m-it-Q8_0.gguf
- llama.cpp server options and schema-constrained responses: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp release attestation: https://github.com/ggml-org/llama.cpp/attestations/44990064
