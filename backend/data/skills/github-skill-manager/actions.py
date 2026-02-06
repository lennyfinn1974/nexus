import subprocess
from typing import Dict, List, Optional

def create_note(title: str, content: str, folder: str = "Notes") -> Dict:
    \"\"\"Create a new note in Apple Notes.\"\"\"
    
    title_escaped = title.replace('"', '\\"')
    content_escaped = content.replace('"', '\\"')
    folder_escaped = folder.replace('"', '\\"')
    
    script = f'''
    tell application "Notes"
        activate
        try
            set targetFolder to folder "{folder_escaped}"
        on error
            set targetFolder to folder "Notes"
        end try
        
        set newNote to make new note in targetFolder
        set name of newNote to "{title_escaped}"
        set body of newNote to "{content_escaped}"
        
        return id of newNote
    end tell
    '''
    
    try:
        result = subprocess.run(['osascript', '-e', script]