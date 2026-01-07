# Demucs Audio Separation - Vast.ai Template

Template Docker pour Vast.ai avec Demucs pour la separation audio (vocals/instrumental).

## Fonctionnalites

- **Demucs** pour separation vocals/instruments
- **ONNX Runtime GPU** pour inference rapide
- **PyTorch + CUDA** (pre-cache sur Vast.ai)
- **CLI simple** `demucs-separate`
- **Auto-segmentation** par defaut 5 minutes max par segment

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

## Configuration Vast.ai

| Champ | Valeur |
|-------|--------|
| Docker Image | `ghcr.io/cyrille8000/ffmpeg-demucs-vast-template:latest` |
| On-start Script | `/start.sh` |
| Disk Space | 20 GB minimum |

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
