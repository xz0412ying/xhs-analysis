"""
文本清洗工具
"""
import re


def clean_text(text: str) -> str:
    """
    清洗文本
    
    Args:
        text: 原始文本
        
    Returns:
        str: 清洗后的文本
    """
    if not text:
        return ""
    
    # 去除多余空白字符
    text = text.strip()
    
    # 去除换行符
    text = text.replace("\n", " ").replace("\r", " ")
    
    # 去除多个连续空格
    text = re.sub(r"\s+", " ", text)
    
    return text


def truncate_text(text: str, max_len: int = 800) -> str:
    """
    截断文本
    
    Args:
        text: 原始文本
        max_len: 最大长度
        
    Returns:
        str: 截断后的文本
    """
    text = clean_text(text)
    
    if len(text) <= max_len:
        return text
    
    return text[:max_len] + "..."


def extract_urls(text: str) -> list:
    """
    提取文本中的URL
    
    Args:
        text: 原始文本
        
    Returns:
        list: URL列表
    """
    url_pattern = r'https?://[^\s]+'
    return re.findall(url_pattern, text)


def remove_special_chars(text: str) -> str:
    """
    移除特殊字符
    
    Args:
        text: 原始文本
        
    Returns:
        str: 移除特殊字符后的文本
    """
    # 保留中文、英文、数字和常见标点
    pattern = r'[^\u4e00-\u9fa5a-zA-Z0-9\s.,!?;:()\'"\-]'
    return re.sub(pattern, "", text)
