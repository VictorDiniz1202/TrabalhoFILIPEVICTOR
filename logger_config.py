import logging
import os
from datetime import date
from pathlib import Path

ActiveLoggers = {}

class Log:
    def __init__(self, Name):
        #cria a pasta log
        self.log_path = Path("logs")
        self.log_path.mkdir(exist_ok=True)
        
        file_path = self.log_path / f'{Name}_{date.today()}.log'

        self.c_handler = logging.StreamHandler()  # Console
        # Adicionei utf-8, que é eficaz ao trabalhar com emojis(evita travar o bot, pois o log nao abria)
        self.f_handler = logging.FileHandler(filename=file_path, mode='a', encoding='utf-8') 
        
        self.c_handler.setLevel(logging.INFO)
        self.f_handler.setLevel(logging.INFO)
        
        log_format = logging.Formatter(fmt=f'%(asctime)s - %(levelname)s - %(name)s - %(message)s', datefmt='%d-%m-%y %H:%M:%S')
        
        self.c_handler.setFormatter(log_format)
        self.f_handler.setFormatter(log_format)

    def get_logger(self, name):
        if ActiveLoggers.get(name):
            return ActiveLoggers.get(name)
        else:
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            
            if not logger.handlers:
                logger.addHandler(self.c_handler)
                logger.addHandler(self.f_handler)
            
            ActiveLoggers[name] = logger
            return logger