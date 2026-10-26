python3 command2label.py --dockerfile Dockerfile command.json
# Disable provenance/SBOM attestations so the push is a single image manifest, not an
# index; an amd64-only index can't be pulled on other hosts (e.g. arm64) without --platform
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
    -t xnatworks/dcm2bids-session:2.18 \
    -t xnatworks/dcm2bids-session:latest \
    --push .
