"""SSL 证书管理器

负责生成、信任、更新自签名证书，用于 HTTPS 流量解密。
"""

import os
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger


class CertificateManager:
    """SSL 证书管理器

    自动生成自签名根证书并添加到 Windows 信任存储，确保 mitmproxy 能解密 HTTPS 流量。
    """

    def __init__(self, cert_dir: str = ".certs"):
        """初始化证书管理器

        Args:
            cert_dir: 证书存储目录
        """
        self.cert_dir = Path(cert_dir)
        self.cert_dir.mkdir(parents=True, exist_ok=True)

    def generate_certificate(self, hostname: str = "danmaku-listener") -> Tuple[str, str]:
        """生成自签名证书

        Args:
            hostname: 证书通用名称

        Returns:
            (cert_path, key_path) 元组
        """
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        # 生成私钥
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # 生成证书
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # 保存证书和私钥
        cert_path = self.cert_dir / f"{hostname}.pem"
        key_path = self.cert_dir / f"{hostname}.key"

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        with open(key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )

        logger.info(f"Generated certificate: {cert_path}")
        return str(cert_path), str(key_path)

    def trust_certificate(self, cert_path: str) -> bool:
        """将证书添加到系统信任存储（Windows）

        Args:
            cert_path: 证书文件路径

        Returns:
            True 如果成功
        """
        try:
            import subprocess
            import platform

            if platform.system() != "Windows":
                logger.warning("Trusting certificates is only supported on Windows")
                return False

            # 使用 certutil 添加证书到受信任的根证书颁发机构
            cmd = [
                "certutil",
                "-addstore",
                "Root",
                cert_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Successfully trusted certificate: {cert_path}")
                return True
            else:
                logger.error(f"Failed to trust certificate: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error trusting certificate: {e}")
            return False

    def cleanup(self) -> None:
        """清理证书目录"""
        if self.cert_dir.exists():
            for file in self.cert_dir.glob("*"):
                if file.is_file():
                    file.unlink()
            logger.info("Cleaned up certificate directory")