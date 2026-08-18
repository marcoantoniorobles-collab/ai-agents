from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Coinciden con las variables ya definidas en ~/ai-agents/.env
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # Nombres de servicio dentro de la red interna "ai-network" (no IPs)
    database_host: str = "postgres"
    database_port: int = 5432
    redis_host: str = "redis"
    redis_port: int = 6379

    # Parámetros del monitor de heartbeat (Agent Manager interno)
    heartbeat_timeout_seconds: int = 60
    heartbeat_check_interval_seconds: int = 15

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
