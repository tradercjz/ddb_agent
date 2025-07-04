from abc import ABC, abstractmethod
import os
from typing import Optional

# --- 抽象基类 ---
class BaseTextExtractor(ABC):
    """
    Abstract base class for all text extraction strategies.
    """
    @abstractmethod
    def extract(self, file_path: str) -> Optional[str]:
        """
        Extracts plain text content from a given file.

        Args:
            file_path: The path to the file.

        Returns:
            The extracted text content as a string, or None if extraction fails.
        """
        pass

# --- 具体实现子类 ---

class PlainTextExtractor(BaseTextExtractor):
    """Extracts text from plain text files (.txt, .md, .py, .dos, etc.)."""
    def extract(self, file_path: str) -> Optional[str]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading plain text file {file_path}: {e}")
            return None

class PDFExtractor(BaseTextExtractor):
    """Extracts text from PDF files using the PyMuPDF library."""
    def __init__(self):
        try:
            import fitz  # PyMuPDF
            self.fitz = fitz
        except ImportError:
            raise ImportError(
                "PyMuPDF is not installed. Please install it with `pip install PyMuPDF` to support PDF files."
            )

    def extract(self, file_path: str) -> Optional[str]:
        try:
            text_content = []
            with self.fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc):
                    # 添加页码分隔符，为上下文提供更多信息
                    text_content.append(f"\n--- Page {page_num + 1} ---\n")
                    text_content.append(page.get_text())
            return "".join(text_content)
        except Exception as e:
            print(f"Error extracting text from PDF {file_path}: {e}")
            return None

class DOCXExtractor(BaseTextExtractor):
    """Extracts text from DOCX files using the python-docx library."""
    def __init__(self):
        try:
            import docx
            self.docx = docx
        except ImportError:
            raise ImportError(
                "python-docx is not installed. Please install it with `pip install python-docx` to support DOCX files."
            )

    def extract(self, file_path: str) -> Optional[str]:
        try:
            doc = self.docx.Document(file_path)
            full_text = [para.text for para in doc.paragraphs]
            return '\n'.join(full_text)
        except Exception as e:
            print(f"Error extracting text from DOCX {file_path}: {e}")
            return None

# --- 工厂函数 ---

# 缓存已创建的提取器实例，避免重复初始化
_EXTRACTOR_CACHE = {}

def get_extractor(file_path: str) -> Optional[BaseTextExtractor]:
    """
    Factory function that returns the appropriate text extractor based on the file extension.
    """
    _, extension = os.path.splitext(file_path)
    extension = extension.lower()

    # 首先检查缓存
    if extension in _EXTRACTOR_CACHE:
        return _EXTRACTOR_CACHE[extension]

    extractor: Optional[BaseTextExtractor] = None
    if extension in ['.txt', '.md', '.markdown', '.py', '.js', '.ts', '.html', '.css', '.dos', '.json', '.xml']:
        extractor = PlainTextExtractor()
    elif extension == '.pdf':
        try:
            extractor = PDFExtractor()
        except ImportError as e:
            print(e) # 打印安装提示
    elif extension == '.docx':
        try:
            extractor = DOCXExtractor()
        except ImportError as e:
            print(e)
    # 未来可以轻松扩展
    # elif extension in ['.ppt', '.pptx']:
    #     extractor = PPTExtractor()
    else:
        # 对于未知类型，可以默认使用纯文本方式尝试，或者直接返回None
        print(f"Warning: No specific extractor for '{extension}'. Falling back to PlainTextExtractor.")
        extractor = PlainTextExtractor()

    # 存入缓存
    if extractor:
        _EXTRACTOR_CACHE[extension] = extractor
    
    return extractor

# --- 统一的调用接口 ---

def extract_text_from_file(file_path: str) -> Optional[str]:
    """
    A single entry point to extract text from any supported file type.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None
        
    extractor = get_extractor(file_path)
    if extractor:
        return extractor.extract(file_path)
    
    print(f"No suitable extractor found for file: {file_path}")
    return None