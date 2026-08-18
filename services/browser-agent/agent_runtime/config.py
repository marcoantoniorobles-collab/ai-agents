from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    postgres_db: str
    postgres_user: str
    postgres_password: str

    database_host: str = "postgres"
    database_port: int = 5432
    redis_host: str = "redis"
    redis_port: int = 6379

    # Cada contenedor de este tipo es UN agente. El nombre lo define el
    # docker-compose vía variable de entorno AGENT_NAME (ej. "agent-1").
    agent_name: str

    heartbeat_interval_seconds: int = 15

    # Si es True, el Chromium arranca headed (visible) dentro del display
    # Xvfb, y start.sh expone ese display por noVNC en el puerto 6080.
    enable_vnc: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.database_host}:{self.database_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


settings = Settings()
