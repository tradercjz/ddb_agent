"""
简单的 API 测试脚本
用于验证 LLM API 配置是否正确，以及基本调用是否工作
"""

import os
from dotenv import load_dotenv
from llm.models import ModelManager
from llm.llm_client import LLMClientManager

# 加载环境变量
load_dotenv()

def test_api_direct():
    """直接测试 API 调用（不使用装饰器）"""
    print("=" * 60)
    print("测试 1: 直接调用 LLM API")
    print("=" * 60)
    
    # 1. 获取默认模型配置
    default_model_name = os.getenv("DEFAULT_LLM_MODEL", "deepseek")
    print(f"✓ 从 .env 读取默认模型: {default_model_name}")
    
    # 2. 从 models.json 获取模型配置
    model_config = ModelManager.get_model_config(default_model_name)
    if not model_config:
        print(f"✗ 错误: 无法找到模型配置 '{default_model_name}'")
        return False
    
    print(f"✓ 找到模型配置:")
    print(f"  - Model Name: {model_config.model_name}")
    print(f"  - Base URL: {model_config.base_url}")
    print(f"  - API Key: {model_config.get_api_key()[:10]}...{model_config.get_api_key()[-10:]}")
    
    # 3. 创建 LLM 客户端
    try:
        llm_client = LLMClientManager.get_client(
            api_key=model_config.get_api_key(),
            base_url=model_config.base_url
        )
        print(f"✓ 成功创建 LLM 客户端")
    except Exception as e:
        print(f"✗ 创建客户端失败: {e}")
        return False
    
    # 4. 发送一个简单的测试请求
    print("\n发送测试请求...")
    test_messages = [
        {"role": "user", "content": "请用一句话回答：1+1等于几？"}
    ]
    
    try:
        response_generator = llm_client.generate_response(
            conversation_history=test_messages,
            model=model_config.model_name,
            log_requests=False
        )
        
        print("✓ API 请求已发送，正在接收响应...\n")
        
        # 消耗 generator 并收集响应
        content_parts = []
        reasoning_parts = []
        
        try:
            while True:
                chunk = next(response_generator)
                if chunk.type == "content":
                    content_parts.append(chunk.data)
                    print(chunk.data, end="", flush=True)
                elif chunk.type == "reasoning":
                    reasoning_parts.append(chunk.data)
        except StopIteration as e:
            final_response = e.value
            print("\n")
            
            # 检查响应
            if final_response.success:
                print(f"✓ API 调用成功!")
                print(f"  - 响应长度: {len(final_response.content)} 字符")
                print(f"  - 响应内容: {final_response.content}")
                if final_response.reasoning_content:
                    print(f"  - 推理内容长度: {len(final_response.reasoning_content)} 字符")
                return True
            else:
                print(f"✗ API 调用失败:")
                print(f"  - 错误类型: {final_response.error_type}")
                print(f"  - 错误信息: {final_response.error_message}")
                return False
                
    except Exception as e:
        print(f"\n✗ 请求过程中出错: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_api_with_decorator():
    """测试使用装饰器的 API 调用"""
    print("\n" + "=" * 60)
    print("测试 2: 使用 @llm.prompt() 装饰器")
    print("=" * 60)
    
    from llm.llm_prompt import llm
    
    @llm.prompt()
    def simple_test(question: str):
        """
        请用一句话回答以下问题：{{ question }}
        """
        return {
            "question": question
        }
    
    print("✓ 装饰器函数已定义")
    print("发送测试请求...\n")
    
    try:
        response_generator = simple_test("1+1等于几？")
        
        # 消耗 generator
        try:
            while True:
                chunk = next(response_generator)
                if chunk.type == "content":
                    print(chunk.data, end="", flush=True)
        except StopIteration as e:
            final_response = e.value
            print("\n")
            
            if final_response.success:
                print(f"✓ 装饰器调用成功!")
                print(f"  - 响应长度: {len(final_response.content)} 字符")
                print(f"  - 响应内容: {final_response.content}")
                return True
            else:
                print(f"✗ 装饰器调用失败:")
                print(f"  - 错误类型: {final_response.error_type}")
                print(f"  - 错误信息: {final_response.error_message}")
                return False
                
    except Exception as e:
        print(f"\n✗ 装饰器调用出错: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_json_response():
    """测试 JSON 格式的响应（模拟 text_index_manager 的场景）"""
    print("\n" + "=" * 60)
    print("测试 3: JSON 格式响应（模拟索引创建场景）")
    print("=" * 60)
    
    from llm.llm_prompt import llm
    from utils.json_parser import parse_json_string
    
    @llm.prompt()
    def test_json_format():
        """
        请返回以下 JSON 格式的内容，不要添加任何额外的文字：
        
        ```json
        {
          "status": "success",
          "message": "这是一个测试",
          "data": [1, 2, 3]
        }
        ```
        """
        return {}
    
    print("✓ JSON 测试函数已定义")
    print("发送测试请求...\n")
    
    try:
        response_generator = test_json_format()
        
        # 消耗 generator
        try:
            while True:
                chunk = next(response_generator)
                if chunk.type == "content":
                    print(chunk.data, end="", flush=True)
        except StopIteration as e:
            final_response = e.value
            print("\n")
            
            if not final_response.success:
                print(f"✗ API 调用失败: {final_response.error_message}")
                return False
            
            print(f"✓ 收到响应，长度: {len(final_response.content)} 字符")
            print(f"响应内容:\n{final_response.content}\n")
            
            # 尝试解析 JSON
            json_content = parse_json_string(final_response.content)
            
            if json_content is None:
                print("✗ JSON 解析失败")
                return False
            else:
                print("✓ JSON 解析成功:")
                print(f"  {json_content}")
                return True
                
    except Exception as e:
        print(f"\n✗ JSON 测试出错: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n🔍 开始 LLM API 配置测试\n")
    
    results = []
    
    # 测试 1: 直接调用
    result1 = test_api_direct()
    results.append(("直接 API 调用", result1))
    
    if result1:
        # 测试 2: 装饰器调用
        result2 = test_api_with_decorator()
        results.append(("装饰器调用", result2))
        
        if result2:
            # 测试 3: JSON 响应
            result3 = test_json_response()
            results.append(("JSON 格式响应", result3))
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status} - {test_name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！API 配置正确。")
    else:
        print("\n⚠️  部分测试失败，请检查上面的错误信息。")

