# Demucs Audio Separation - Vast.ai Template

Template Docker pour Vast.ai avec Demucs pour la separation audio (vocals/instrumental).

## Fonctionnalites

- **Demucs** pour separation vocals/instruments
- **ONNX Runtime GPU** pour inference rapide
- **PyTorch + CUDA** (pre-cache sur Vast.ai)
- **CLI simple** `demucs-separate`
- **API REST** sur port 8185 pour integration programmatique
- **Auto-segmentation** par defaut 5 minutes max par segment
- **Progress tracking** via `progress.txt` (JSON) pour API polling
- **Output final** instrumental concatene en MP3 mono

## Usage

### CLI demucs-separate

```bash
# Depuis une URL (publique ou signee)
# Auto-decoupe en segments de 5 minutes max
demucs-separate --input "https://example.com/audio.mp3" --output ./results

# Avec decoupage par intervalles personnalises (timestamps en secondes)
# Cree segments: [0->300s], [300s->600s], [600s->900s], [900s->FIN]
demucs-separate --input "https://..." --interval-cut "300,600,900" --output ./results

# Depuis un fichier local
demucs-separate --input /path/to/audio.wav --output ./results

# Extraire tous les stems (vocals, drums, bass, other)
demucs-separate --input audio.mp3 --output ./results --all-stems

# Aide
demucs-separate --help
```

### Python direct

```bash
cd /workspace/mvsep

python3 inference_demucs.py \
    --input_audio audio.mp3 \
    --output_folder ./results \
    --only_vocals \
    --large_gpu
```

### API REST (port 8185)

Le serveur FastAPI demarre automatiquement et expose les endpoints suivants:

```bash
# Health check
curl http://localhost:8185/health

# Statut serveur (models_ready, jobs actifs)
curl http://localhost:8185/status

# Creer un job de separation
curl -X POST http://localhost:8185/job \
  -H "Content-Type: application/json" \
  -d '{"input_url": "https://example.com/audio.mp3"}'

# Avec intervalles personnalises
curl -X POST http://localhost:8185/job \
  -H "Content-Type: application/json" \
  -d '{"input_url": "https://...", "interval_cut": "300,600,900"}'

# Verifier le statut d'un job
curl http://localhost:8185/job/{job_id}

# Telecharger le resultat
curl -o instrumental.mp3 http://localhost:8185/result/{job_id}

# Lister tous les jobs
curl http://localhost:8185/jobs
```

### Client RunPod (usage local)

Le fichier `runpod_client.py` permet d'automatiser le workflow complet:

```bash
# Configurer la cle API
export RUNPOD_API_KEY="your_api_key"

# Lister les GPUs disponibles
python runpod_client.py gpus

# Lancer une separation (demarre pod, execute job, telecharge resultat, arrete pod)
python runpod_client.py separate "https://example.com/audio.mp3" --output ./results

# Avec intervalles personnalises
python runpod_client.py separate "https://..." --interval-cut "300,600,900"

# Garder le pod actif apres le job
python runpod_client.py separate "https://..." --keep-pod

# Arreter un pod manuellement
python runpod_client.py stop --pod-id <pod_id>
```

## Configuration Vast.ai

| Champ | Valeur |
|-------|--------|
| Docker Image | `ghcr.io/cyrille8000/ffmpeg-demucs-vast-template:latest` |
| On-start Script | `/start.sh` |
| Disk Space | 20 GB minimum |

## Output

```
./results/
├── progress.txt           # Etat de progression (JSON) pour API polling
├── instrumental.mp3       # Instrumental final concatene (mono)
├── segments/              # Segments audio decoupes
│   ├── segment_000.m4a
│   ├── segment_001.m4a
│   └── ...
└── demucs_results/        # Resultats Demucs par segment
    ├── segment_000_vocals.wav
    ├── segment_000_instrum.wav
    └── ...
```

### Format progress.txt

```json
{
  "state": "demucs",
  "tasks": {
    "models": "done",
    "cutting": "no_work",
    "inference": "running",
    "conversion": "no_work"
  },
  "timestamp": 1704067200.0,
  "elapsed_seconds": 45.2,
  "details": {
    "models_ready": true,
    "completed_segments": 2,
    "total_segments": 4,
    "percent": 50.0
  }
}
```

**Etats globaux:** `idle`, `demucs`, `completed`, `error`

**Etats des taches:**
- `tasks.models` - `done` si modeles extraits, `no_work` sinon
- `tasks.cutting` - `running` ou `no_work`
- `tasks.inference` - `running` ou `no_work`
- `tasks.conversion` - `running` ou `no_work`

## Structure

```
/workspace/
├── mvsep/
│   ├── inference_demucs.py    # Script principal
│   ├── models/                 # Modeles ML
│   └── results/                # Resultats
└── model_weights/              # Poids compresses

/models-cache/                  # Modeles extraits
```

## Premier demarrage

Les modeles sont extraits automatiquement (~2 minutes).
Les demarrages suivants sont instantanes.

## License

MIT
