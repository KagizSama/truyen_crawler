import re
from typing import List

class TextProcessor:
    @staticmethod
    def clean_text(text: str) -> str:
        if not text:
            return ""
        
        # Remove multiple newlines and spaces
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        
        # Clean specific Vietnamese novel site artifacts if any
        artifacts = [
            "Truyện được cập nhật sớm nhất tại TruyenFull.vn",
            "Chúc bạn có những giây phút thư giãn vui vẻ!",
            "---"
        ]
        for art in artifacts:
            text = text.replace(art, "")
            
        return text.strip()

    @staticmethod
    def chunk_text(text: str, max_chars: int = 1500, overlap: int = 200) -> List[str]:
        if not text:
            return []
            
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + max_chars
            
            # If not at the end, try to find a newline or space to break nicely
            if end < len(text):
                # Look for last newline in the potential chunk
                last_newline = text.rfind('\n', start, end)
                if last_newline > start + (max_chars // 2):
                    end = last_newline
                else:
                    # Look for last space
                    last_space = text.rfind(' ', start, end)
                    if last_space > start + (max_chars // 2):
                        end = last_space
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            # Move start forward by (actual_end - overlap)
            start = end - overlap
            if start < 0: start = 0
            
            # Safety break if we aren't moving
            if end >= len(text):
                break
                
        return chunks
