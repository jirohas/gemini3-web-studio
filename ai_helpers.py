import os
import streamlit as st
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential

# GitHub Models経由でo4-miniを呼び出す関数
def think_with_o4mini(user_question: str, research_text: str) -> str:
    """
    GitHub Models (Azure AI Inference) 経由で o4-mini を使って独立した回答案を作成
    """
    try:
        # GitHub Token取得（st.secrets優先）
        if "GITHUB_TOKEN" in st.secrets:
            github_token = st.secrets["GITHUB_TOKEN"]
        else:
            github_token = os.getenv("GITHUB_TOKEN", "")
        
        if not github_token:
            return "[o3-mini Error] GitHub Token が設定されていません"
        
        # Azure AI Inference Client
        endpoint = "https://models.inference.ai.azure.com"
        client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(github_token)
        )
        
        # プロンプト構築
        user_content = (
            f"ユーザーの質問:\n{user_question}\n\n"
            f"調査メモ:\n{research_text}\n\n"
            "指示:\n"
            "あなたは o4-mini として、調査メモを元に独立した回答案を作成してください。\n"
            "特に以下の点に注意してください:\n"
            "1. 論理的な推論の深さ\n"
            "2. 見落とされがちなエッジケース\n"
            "3. 前提条件の妥当性\n"
        )
        
        # API呼び出し
        response = client.complete(
            messages=[
                {"role": "user", "content": user_content}
            ],
            model="o4-mini",  # GitHub Modelsのモデル名
            temperature=0.7,
            max_tokens=2000
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        return f"[o4-mini Error] {str(e)}"


# AWS Bedrock経由でClaude 4.5を呼び出す関数
def review_with_claude45(user_question: str, gemini_answer: str, research_text: str) -> str:
    """
    AWS Bedrock 経由で Claude 4.5 Sonnet を使って最終レビュー
    """
    try:
        import boto3
        import json
        
        # AWS認証情報取得（st.secrets優先）
        if "AWS_ACCESS_KEY_ID" in st.secrets:
            aws_access_key = st.secrets["AWS_ACCESS_KEY_ID"]
            aws_secret_key = st.secrets["AWS_SECRET_ACCESS_KEY"]
        else:
            aws_access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
            aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        
        if not aws_access_key or not aws_secret_key:
            return "[Claude 4.5 Error] AWS認証情報が設定されていません"
        
        # Bedrock Clientの作成
        bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name='us-east-1',  # Claude 4.5対応リージョン
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )
        
        # プロンプト構築
        user_content = (
            f"ユーザーの質問:\n{user_question}\n\n"
            f"調査メモ:\n{research_text}\n\n"
            f"Geminiの回答:\n{gemini_answer}\n\n"
            "指示:\n"
            "あなたは Claude 4.5 Sonnet として、Geminiの回答を厳格にレビューしてください。\n"
            "特に以下の点をチェック:\n"
            "1. 事実誤認はないか\n"
            "2. 論理的な飛躍はないか\n"
            "3. リスクの見落としはないか\n"
            "4. 改善できる点はあるか\n"
        )
        
        # Bedrock API呼び出し（Claude 3.5形式）
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            "temperature": 0.5
        })
        
        response = bedrock.invoke_model(
            modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",  # Claude 4.5相当
            body=body
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
        
    except Exception as e:
        return f"[Claude 4.5 Error] {str(e)}"
