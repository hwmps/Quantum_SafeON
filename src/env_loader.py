# -*- coding: utf-8 -*-
"""프로젝트 루트 .env 로더 — 의존성 없이 KMA_API_KEY / IONQ_API_KEY 등을 환경변수로 주입.

이미 설정된 환경변수는 덮어쓰지 않는다. 키는 .env(git 제외)에만 기록할 것.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def load_env(path=ENV_PATH):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


load_env()
