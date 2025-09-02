from rag.embedding_models import VolcanoEmbedding


try:
    embedding_model = VolcanoEmbedding()
    print("VolcanoEmbedding model initialized successfully.")
except ValueError as e:
    print(f"Fatal Error: Could not initialize embedding model. {e}")
    print("Please ensure the ARK_API_KEY environment variable is set.")
except Exception as e:
    print(f"Unexpected error initializing embedding model: {e}")

batch_embeddings = embedding_model.embed_documents(["集群卡住怎么办","DolphinDB 提供了两种 Grafana 数据源插件，其中 dolphindb-datasource-next 插件新增了多项功能、优化和故障修复，而 dolphindb-datasource 插件已停止维护。"])
print(batch_embeddings)