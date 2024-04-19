from aiohttp import web
import json
import time
import requests

async def fetch(req):
    if req.method == "OPTIONS":
        return web.Response(body="", headers={'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*'}, status=204)

    # 解析请求数据
    body = await req.json()

    messages = body.get("messages", [])
    stream = body.get("stream", True)
    model_name = body.get("model", "reka-core")

    # 构造新的请求体
    conversation_history = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "assistant":
            conversation_history.append({"type": "model", "text": content})
        else:
            conversation_history.append({"type": "human", "text": content})

    chat_data = {
        "conversation_history": conversation_history,
        "stream": stream,
        "use_search_engine": False,
        "use_code_interpreter": False,
        "model_name": model_name,
        "random_seed": int(time.time())
    }

    # 处理请求数据
    url = "https://chat.reka.ai/api/chat"
    token = req.headers.get('Authorization', '')  # 从请求头中获取授权令牌
    headers = {
        'Content-Type': 'application/json',
        'Authorization': token
    }  # 设置HTTP头部

    try:
        # 设置超时时间为 30 秒
        response = requests.post(url, headers=headers, data=json.dumps(chat_data), stream=True, timeout=30)
    except requests.exceptions.Timeout:
        print("Request to chat.reka.ai timed out")
        return web.Response(status=504)  # Gateway Timeout
    except ConnectionResetError:
        print("Connection reset by peer")
        return web.Response(status=500)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return web.Response(status=500)  # Internal Server Error

    previous_length = 0
    response_stream = web.StreamResponse()
    response_stream.headers['Content-Type'] = 'text/event-stream'
    response_stream.headers['Access-Control-Allow-Origin'] = '*'  # 允许所有来源的跨域请求
    response_stream.headers['Access-Control-Allow-Headers'] = '*'  # 允许所有类型的头部字段
    await response_stream.prepare(req)
    writer = response_stream

    try:
        for line in response.iter_lines():
            if line:  # 过滤掉 keep-alive 的新行
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    data_content = decoded_line[5:].strip()
                    data_json = json.loads(data_content)
                    if data_json['type'] == 'model':
                        current_text = data_json['text']
                        new_text = current_text[previous_length:]
                        previous_length = len(current_text)
                        # 创建新的JSON对象
                        new_json = {
                            "id": "chatcmpl-123456789",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": new_text
                                    },
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                                "total_tokens": 0
                            },
                        }

                        # 将新的JSON对象作为流式响应返回给客户端，每行一个响应
                        event_data = f"data: {json.dumps(new_json, ensure_ascii=False)}\n\n"
                        await writer.write(event_data.encode('utf-8'))

    except Exception as e:
        print(f"Unexpected error while processing response: {e}")
        return web.Response(status=500)  # Internal Server Error

    return writer

async def onRequest(request):
    return await fetch(request)

app = web.Application()
app.router.add_route("*", "/v1/chat/completions", onRequest)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=3031)
