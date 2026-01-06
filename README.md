# FFmpeg + Demucs Vast.ai Template

Template Docker optimise pour Vast.ai avec FFmpeg (NVENC) et Demucs pour la separation audio.

## Contenu

- **PyTorch 2.4** + CUDA 12.4 (pre-cache sur Vast.ai)
- **FFmpeg** avec support NVENC complet (h264, hevc, av1)
- **Demucs** pour separation vocals/instruments
- **ONNX Runtime GPU** pour inference rapide
- **JupyterLab** pour developpement interactif

## Taille de l'image

| Composant | Taille |
|-----------|--------|
| Base Vast.ai (PyTorch + CUDA) | ~4 GB (cache) |
| FFmpeg + packages Python | ~1 GB |
| Poids des modeles (compresses) | ~2 GB |
| **Total** | **~7 GB** |

## Premier demarrage

Au premier lancement, les modeles sont automatiquement extraits (~2 minutes).
Les demarrages suivants sont instantanes.

## Usage sur Vast.ai

### 1. Creer un template

1. Aller sur [Vast.ai Templates](https://cloud.vast.ai/templates/)
2. Cliquer "Edit Image & Config"
3. Configurer:
   - **Docker Image**: `ghcr.io/cyrille8000/ffmpeg-demucs-vast-template:latest`
   - **Docker Options**: `-p 8888:8888`
   - **On-start Script**: `/start.sh`
   - **Disk Space**: 20 GB minimum

### 2. Lancer une instance

1. Selectionner le template
2. Choisir un GPU (RTX 3090, 4090 recommande)
3. Lancer

### 3. Utiliser Demucs

```bash
cd /workspace/mvsep

# Separation vocals/instruments
python3 inference_demucs.py \
    --input_audio votre_audio.mp3 \
    --output_folder ./results \
    --only_vocals \
    --large_gpu
```

### 4. Utiliser le CLI ffmpeg-demucs

```bash
# Telecharger depuis YouTube et separer
ffmpeg-demucs --input-url-youtube "https://youtube.com/watch?v=xxx" --output ./results

# Avec cookies (videos age-restricted)
ffmpeg-demucs --input-url-youtube "https://..." --file-cookie "https://url/cookies.txt" --output ./results

# Avec intervalles specifiques
ffmpeg-demucs --input-url-youtube "https://..." --interval-cut "5.6,475.1,800.5" --output ./results

# Fichier local
ffmpeg-demucs --input-file audio.mp3 --only-vocals --output ./results

# Aide
ffmpeg-demucs --help
```

### 5. Utiliser FFmpeg avec NVENC

```bash
# Encoder en H.264 GPU
ffmpeg -i input.mp4 -c:v h264_nvenc -preset p4 output.mp4

# Encoder en AV1 GPU (RTX 40 series)
ffmpeg -i input.mp4 -c:v av1_nvenc -preset p1 output.webm
```

## Variables d'environnement

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | (interne) | URL des poids des modeles |

## Structure des fichiers

```
/workspace/
├── mvsep/
│   ├── inference_demucs.py    # Script principal
│   ├── models/                 # Symlinks vers modeles
│   └── results/                # Resultats separation
├── model_weights/              # Poids compresses
└── ...

/models-cache/                  # Modeles extraits
├── Kim_Vocal_2.onnx
├── Kim_Inst.onnx
└── *.th (Demucs checkpoints)
```

## Build local

```bash
docker build -t ffmpeg-demucs-vast-template .
docker run --gpus all -p 8888:8888 ffmpeg-demucs-vast-template
```

## Differences avec le template RunPod

| Aspect | RunPod | Vast.ai |
|--------|--------|---------|
| Image de base | `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` | `vastai/pytorch:2.4.1-cuda-12.4.1-py311-22.04` |
| Registry | GHCR | GHCR |
| Configuration | RunPod Templates | Vast.ai Templates |

## License

MIT
