## How to build
- Create PAT on [Github](https://github.com/settings/tokens)
- On the local machine
$ export CR_PAT=YOUR_TOKEN
$ echo $CR_PAT | docker login ghcr.io -u hkuehl --password-stdin
$ docker push ghcr.io/hkuehl/byd-hvs-hvm-prometheus-exporter:latest

Before that, build the image locally:
$ docker build . -t ghcr.io/hkuehl/byd-hvs-hvm-prometheus-exporter:latest
