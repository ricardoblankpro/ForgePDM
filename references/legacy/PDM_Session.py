# -*- coding: utf-8 -*-
"""
PDM Session Manager
Handles user authentication and session management.
"""

import os
import getpass
import json
from datetime import datetime
from PySide import QtGui, QtCore


class PDMSession:
    """Singleton class to manage PDM session"""
    
    _instance = None
    _current_user = None
    _session_start = None
    _is_authenticated = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PDMSession, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = PDMSession()
        return cls._instance
    
    @classmethod
    def get_system_username(cls):
        """Get the current OS username"""
        try:
            return getpass.getuser()
        except Exception:
            return os.environ.get('USERNAME') or os.environ.get('USER') or 'Unknown'
    
    @classmethod
    def is_authenticated(cls):
        """Check if user is authenticated"""
        return cls._is_authenticated
    
    @classmethod
    def get_current_user(cls):
        """Get current authenticated user"""
        return cls._current_user
    
    @classmethod
    def login(cls, config_path=None):
        """
        Authenticate user.
        Returns True if successful, False otherwise.
        """
        if cls._is_authenticated:
            return True
        
        system_user = cls.get_system_username()
        
        # Load allowed users from config if provided
        allowed_users = None
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    allowed_users = config.get('users', [])
            except Exception:
                pass
        
        # Show login dialog
        dialog = PDMLoginDialog(system_user, allowed_users)
        result = dialog.exec_()
        
        if result == QtGui.QDialog.Accepted:
            cls._current_user = dialog.get_selected_user()
            cls._session_start = datetime.now()
            cls._is_authenticated = True
            return True
        
        return False
    
    @classmethod
    def logout(cls):
        """End current session"""
        cls._current_user = None
        cls._session_start = None
        cls._is_authenticated = False
    
    @classmethod
    def require_login(cls, config_path=None):
        """
        Decorator/function to ensure user is logged in.
        Returns current user if authenticated, None otherwise.
        """
        if not cls._is_authenticated:
            if not cls.login(config_path):
                return None
        return cls._current_user


class PDMLoginDialog(QtGui.QDialog):
    """Login dialog for PDM system"""
    
    def __init__(self, system_user, allowed_users=None, parent=None):
        super(PDMLoginDialog, self).__init__(parent)
        
        self.system_user = system_user
        self.allowed_users = allowed_users or []
        self.selected_user = None
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface"""
        
        self.setWindowTitle("PDM Login")
        self.setMinimumWidth(350)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        
        layout = QtGui.QVBoxLayout()
        
        # Header
        header_label = QtGui.QLabel("PDM System Login")
        header_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        header_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # System user info
        info_group = QtGui.QGroupBox("Detected User")
        info_layout = QtGui.QFormLayout()
        
        self.lbl_system_user = QtGui.QLabel(self.system_user)
        self.lbl_system_user.setStyleSheet("font-weight: bold;")
        info_layout.addRow("System Username:", self.lbl_system_user)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # User selection
        select_group = QtGui.QGroupBox("Confirm Identity")
        select_layout = QtGui.QVBoxLayout()
        
        # Option 1: Use system username
        self.radio_system = QtGui.QRadioButton(f"Login as: {self.system_user}")
        self.radio_system.setChecked(True)
        select_layout.addWidget(self.radio_system)
        
        # Option 2: Select from list (if allowed_users provided)
        if self.allowed_users:
            self.radio_select = QtGui.QRadioButton("Select from registered users:")
            select_layout.addWidget(self.radio_select)
            
            self.combo_users = QtGui.QComboBox()
            self.combo_users.addItems(self.allowed_users)
            self.combo_users.setEnabled(False)
            
            # Try to select system user in combo if exists
            index = self.combo_users.findText(self.system_user)
            if index >= 0:
                self.combo_users.setCurrentIndex(index)
            
            select_layout.addWidget(self.combo_users)
            
            # Connect radio buttons
            self.radio_system.toggled.connect(self.on_radio_changed)
            self.radio_select.toggled.connect(self.on_radio_changed)
        
        select_group.setLayout(select_layout)
        layout.addWidget(select_group)
        
        # Warning if user not in allowed list
        if self.allowed_users and self.system_user not in self.allowed_users:
            warning_label = QtGui.QLabel(
                f"⚠ User '{self.system_user}' is not in the registered users list.\n"
                "Please select your name or contact administrator."
            )
            warning_label.setStyleSheet("color: #cc7000; margin: 10px;")
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)
        
        # Buttons
        button_layout = QtGui.QHBoxLayout()
        
        self.btn_login = QtGui.QPushButton("Login")
        self.btn_login.setDefault(True)
        self.btn_cancel = QtGui.QPushButton("Cancel")
        
        button_layout.addStretch()
        button_layout.addWidget(self.btn_login)
        button_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # Connect buttons
        self.btn_login.clicked.connect(self.on_login)
        self.btn_cancel.clicked.connect(self.reject)
    
    def on_radio_changed(self):
        """Handle radio button change"""
        if hasattr(self, 'combo_users'):
            self.combo_users.setEnabled(self.radio_select.isChecked())
    
    def on_login(self):
        """Handle login button click"""
        
        if hasattr(self, 'radio_select') and self.radio_select.isChecked():
            self.selected_user = self.combo_users.currentText()
        else:
            self.selected_user = self.system_user
        
        # Validate user is in allowed list (if list exists)
        if self.allowed_users and self.selected_user not in self.allowed_users:
            result = QtGui.QMessageBox.warning(
                self,
                "Unregistered User",
                f"User '{self.selected_user}' is not registered in the system.\n\n"
                "Do you want to continue anyway?",
                QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
                QtGui.QMessageBox.No
            )
            if result != QtGui.QMessageBox.Yes:
                return
        
        self.accept()
    
    def get_selected_user(self):
        """Get the selected username"""
        return self.selected_user


# Convenience function for other macros
def require_pdm_login(config_path=None):
    """
    Call this at the start of any PDM macro to ensure user is logged in.
    Returns username if authenticated, None otherwise.
    """
    return PDMSession.require_login(config_path)


def get_current_pdm_user():
    """Get current logged in user, or None if not logged in"""
    if PDMSession.is_authenticated():
        return PDMSession.get_current_user()
    return None


def pdm_logout():
    """Log out current user"""
    PDMSession.logout()