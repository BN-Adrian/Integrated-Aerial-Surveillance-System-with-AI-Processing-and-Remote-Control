# Integrated Aerial Surveillance System with AI Processing and Remote Control

A fully custom-built drone surveillance platform with real-time object detection (YOLOv8n + LLaVA-Phi3) and remote control over a private VPN, developed as a master's dissertation at the Faculty of Electronics, Telecommunications and Information Technology — "Gheorghe Asachi" Technical University of Iași.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![YOLOv8](https://img.shields.io/badge/YOLOv8n-Ultralytics-green)
![LLaVA-Phi3](https://img.shields.io/badge/LLaVA--Phi3-Ollama-purple)
![Docker](https://img.shields.io/badge/Docker-CUDA-blue)
![MAVLink](https://img.shields.io/badge/MAVLink-ArduCopter-orange)
![Tailscale](https://img.shields.io/badge/Tailscale-WireGuard-black)

## Overview

This project implements a complete aerial surveillance system in which a custom-built quadrotor drone captures video in real time, streams it to a GPU-equipped processing station for AI inference, and is controlled remotely by an operator from a tablet — all over a private Tailscale mesh network running on top of a 4G connection.

Two pipelines run simultaneously, in opposite directions:
- **Video pipeline**: Camera → Raspberry Pi 5 → Processing PC (YOLO + LLaVA-Phi3) → Laptop → iPad
- **Command pipeline**: iPad → Laptop (joystick) → Raspberry Pi 5 → Pixhawk (MAVLink)

## Features

- **Real-time object detection** with YOLOv8n on GPU (~28–32 ms/frame on an RTX 3070, stable 15 FPS)
- **Detailed vehicle classification** with LLaVA-Phi3 (vision-language model) via Ollama — identifies make and model of vehicles detected by YOLO
- **Video streaming** over Tailscale VPN using ZMQ PUB/SUB with adaptive JPEG compression (80% → 75%)
- **Remote flight control** via joystick, with ZMQ at 120 Hz and MAVLink at 50 Hz to the Pixhawk
- **Failsafe** that resets commands to neutral if no packets arrive for 0.5 seconds
- **Spatial cache** for LLaVA results with 50 px buckets and a 6-second TTL — avoids repeated inference for the same object
- **4G connectivity** between drone and ground station via Tailscale (bypasses carrier-grade NAT)

## Architecture

```
┌─────────────┐    ZMQ:5555    ┌──────────────────┐    ZMQ:5556    ┌─────────────┐    Moonlight    ┌──────┐
│  RPi 5 +    │  ─────────────▶│   Processing PC  │  ─────────────▶│   Laptop    │  ──────────────▶│ iPad │
│  IMX500     │   1280x720     │  YOLOv8n + LLaVA │   854x480      │ Apollo/ZMQ  │                 │      │
│  + 4G modem │   15 FPS       │  RTX 3070 GPU    │   15 FPS       │  Joystick   │◀── commands ────│      │
└──────┬──────┘                └──────────────────┘                └──────┬──────┘                 └──────┘
       │                                                                  │
       │ MAVLink 57600 baud                                                │ ZMQ:5556 (JSON, 120 Hz)
       ▼                                                                  │
┌─────────────┐                                                           │
│  Pixhawk    │◀──────────────────────────────────────────────────────────┘
│  2.4.8      │              Tailscale VPN (WireGuard, over 4G)
│  ArduCopter │
└─────────────┘
```

## Hardware

| Component | Details |
|-----------|---------|
| Frame | S500 (carbon fibre + ABS, 500 mm diagonal) |
| Motors | 4× QX-MOTOR QM2812 brushless |
| ESCs | 4× 30 A |
| Flight controller | Pixhawk 2.4.8 (ArduCopter, STABILIZE mode) |
| Onboard computer | Raspberry Pi 5 (8 GB RAM) |
| Camera | Sony IMX500 (Raspberry Pi AI Camera, 12.3 MP, CSI-2) |
| Connectivity | USB 4G modem |
| Processing station | AMD Ryzen 7 5800X, RTX 3070 8 GB, WSL2 Ubuntu 22.04 |
| Relay | MSI GF62 8RD (Apollo/Sunshine) |
| Operator | iPad 10th gen (Moonlight) |

## Software stack

- **AI**: YOLOv8n (Ultralytics, COCO pretrained weights), LLaVA-Phi3 (CLIP ViT-L/14 encoder + Phi-3 Mini 3.8B decoder, Q4 quantized) served by Ollama
- **Networking**: Tailscale (WireGuard mesh VPN), ZMQ PUB/SUB
- **Containerization**: Docker + NVIDIA Container Toolkit, CUDA 13.2
- **Flight control**: MAVLink (pymavlink), ArduCopter, Mission Planner
- **Video**: Picamera2, OpenCV
- **Input**: Pygame (joystick), Moonlight/Apollo (screen streaming)

## Repository structure

```
.
├── raspberry_pi/
│   ├── stream_video.py          # Capture + ZMQ PUB to PC
│   └── control_direction.py     # ZMQ SUB from laptop → MAVLink to Pixhawk
├── pc/
│   └── yolo_llava.py            # AI pipeline: YOLO + async LLaVA-Phi3
├── laptop/
│   ├── joystick.py              # Joystick read → ZMQ PUB to RPi5
│   └── video_receiver.py        # ZMQ SUB from PC → OpenCV display
└── docker/
    └── docker-compose.yaml      # Tailscale + Ollama with GPU access
```

## Results

The system reached a stable 15 FPS end-to-end pipeline over 4G, with YOLOv8n averaging 28–32 ms per frame on the RTX 3070 and LLaVA-Phi3 returning vehicle make/model in roughly 1–2 seconds asynchronously, without blocking the main detection loop. Tailscale handled NAT traversal reliably across all four nodes (drone, processing PC, laptop, iPad).

The main bottleneck identified during testing was the 4G modem's upload bandwidth, which constrained the video resolution and motivated the choice of 1280×720 at 80% JPEG quality between drone and PC, downscaled to 854×480 at 75% for the final stream to the operator.

## Limitations & future work

- Implement autonomous flight based on YOLO detections, without operator input
- Replace the ZMQ + JPEG pipeline with GStreamer for lower latency
- Add an emergency mode that triggers RTL/LAND automatically on connection loss
- Build a dedicated tablet GUI to replace the Moonlight-based interface
- Evaluate Qwen2.5-VL 3B as a faster replacement for LLaVA-Phi3 on the same GPU

## Author

**Bejan Nelu Adrian** — MSc Information Technologies for Telecommunications, FETTI, "Gheorghe Asachi" Technical University of Iași
Scientific coordinator: Assoc. Prof. Dr. Eng. Hagan Marius Gheorghe

---

*Master's dissertation, 2026.*
