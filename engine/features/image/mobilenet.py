"""MobileNetV2 ImageNet, ONNX Model Zoo, Apache-2.0. Vector previo al clasificador."""
import hashlib
import threading
from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parents[3] / "models/mobilenetv2-12.onnx"
SHA256 = "c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5"
URL = ("https://media.githubusercontent.com/media/onnx/models/main/"
       "validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx")


class MobileNetExtractor:
    def __init__(self, model=MODEL):
        import cv2
        model = Path(model)
        if not model.is_file():
            raise FileNotFoundError("Falta MobileNet. Ejecute python -m engine.features.image.mobilenet")
        if hashlib.sha256(model.read_bytes()).hexdigest() != SHA256:
            raise ValueError("El archivo MobileNet no coincide con el modelo esperado")
        self.net = cv2.dnn.readNetFromONNX(str(model))
        self.lock = threading.Lock()

    def __call__(self, path):
        import cv2
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"No se puede decodificar {path}")
        h, w = img.shape[:2]
        scale = 256 / min(h, w)
        img = cv2.resize(img, (round(w * scale), round(h * scale)))
        h, w = img.shape[:2]
        img = img[(h-224)//2:(h-224)//2+224, (w-224)//2:(w-224)//2+224]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        rgb = (rgb - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
        blob = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])
        try:
            with self.lock:
                self.net.setInput(blob)
                # Tensor de salida de GlobalAveragePool_97 en este ONNX verificado.
                vector = self.net.forward("464").reshape(-1).copy()
        except cv2.error as exc:
            raise ValueError(f"No se pudo extraer el vector MobileNet de {path}") from exc
        norm = np.linalg.norm(vector)
        if vector.size != 1280 or not np.isfinite(vector).all() or norm == 0:
            raise ValueError("MobileNet produjo un vector inválido")
        return vector / norm


def main():
    from tienda.comun import descargar
    descargar(URL, MODEL)
    MobileNetExtractor()
    print(f"Modelo verificado: {MODEL}")


if __name__ == "__main__":
    main()
