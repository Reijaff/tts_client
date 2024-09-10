bl_info = {
    "name": "tts_client",
    "author": "reijaff",
    "description": "",
    "blender": (3, 4, 0),
    "version": (0, 3, 0),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import subprocess
import requests
import hashlib
import base64
import threading
import asyncio
import shutil
import time
import aud
import sys
import os
import bpy
import json


transcription_cache = {}

wm = bpy.context.window_manager


def progress_func():
    tot = 100
    wm.progress_begin(0, tot)
    for i in range(tot):
        wm.progress_update(i)


class TtsClientAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    tts_audio_project_folder: bpy.props.StringProperty(
        name="Folder name for TTS audio",
        description="Folder name for TTS audio in a specific folder alongside blend file",
        default="tts_audio",
    )

    tts_audio_preview_folder: bpy.props.StringProperty(
        name="Common folder path for TTS audio",
        description="Common folder path where TTS audio are stored",
        subtype="DIR_PATH",
        default=os.path.join(bpy.utils.user_resource("DATAFILES"), "tts_audio"),
    )


class TtsClientData(bpy.types.PropertyGroup):
    """Setting per Scene"""

    audio_is_playing: bpy.props.BoolProperty(description="Audio is playing")

    input_text: bpy.props.StringProperty(
        description="Text to synthesize", default="Everything is a test!"
    )

    add_transcription: bpy.props.BoolProperty(
        description="Add transcription", default=True
    )
    speech_speed: bpy.props.FloatProperty(description="Set speech speed", default=1.0)


def tts_output(audio_filepath):
    global pipe_client
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    addon_data = bpy.context.scene.tts_client_data

    addon_prefs.tts_server_status = "processing"

    payload = {
        "text": addon_data.input_text,
        "transcription": addon_data.add_transcription,
        "speed": addon_data.speech_speed,
        # "speaker_id": addon_data.vctk_vits_speaker_idx,
    }
    ret = requests.get("http://127.0.0.1:5300/api/btts", params=payload)
    addon_prefs.tts_server_status = "free"
    ret_data = ret.json()

    with open(audio_filepath, "wb") as f:
        f.write(base64.b64decode(ret_data["audio"]))

    return ret_data["transcription"]


class TTS_Audio_Add(bpy.types.Operator):
    bl_label = "Add"
    bl_idname = "tts_client.tts_audio_add"
    bl_description = "Add sound to the VSE at the current frame"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Start progress thread
        threading.Thread(target=progress_func, args=()).start()

        # Get addon preferences and data
        addon_prefs = context.preferences.addons[__package__].preferences
        addon_data = context.scene.tts_client_data

        # Get input text and preview folder path
        _input_text = addon_data.input_text
        _preview_folder = addon_prefs.tts_audio_preview_folder

        # Check for empty input text
        if not _input_text:
            self.report({"ERROR"}, "Input text is empty")
            return {"FINISHED"}

        # Check if project is saved
        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Project is not saved")
            return {"FINISHED"}

        # Generate audio name using MD5 hash
        audio_name = hashlib.md5(_input_text.encode()).hexdigest() + ".wav"

        # Get audio file paths
        folderpath = os.path.join(
            os.path.dirname(bpy.data.filepath), addon_prefs.tts_audio_project_folder
        )
        audio_filepath = os.path.join(folderpath, audio_name)
        preview_filepath = os.path.join(_preview_folder, audio_name)

        # Create project audio folder if it doesn't exist
        os.makedirs(folderpath, exist_ok=True)

        # Copy audio from preview if it exists
        if os.path.isfile(preview_filepath):
            shutil.copy(preview_filepath, audio_filepath)

        # Generate TTS audio if it doesn't exist
        if not os.path.isfile(audio_filepath):
            transcription_cache[audio_name] = tts_output(audio_filepath)

        # Create sequence editor if it doesn't exist
        if not context.scene.sequence_editor:
            context.scene.sequence_editor_create()

        # Determine the next available channel
        if not context.sequences:
            addSceneChannel = 1
        else:
            addSceneChannel = max(s.channel for s in context.sequences) + 1

        # Add new sound strip to the sequence editor
        newStrip = context.scene.sequence_editor.sequences.new_sound(
            name=os.path.basename(audio_filepath),
            filepath=f"//{addon_prefs.tts_audio_project_folder}/{audio_name}",
            channel=addSceneChannel,
            frame_start=context.scene.frame_current,
        )
        newStrip.show_waveform = True
        newStrip.sound.use_mono = True

        # Add timeline markers based on transcription
        if transcription_cache[audio_name]:
            framerate = context.scene.render.fps
            my_words = [
                word
                for segment in transcription_cache[audio_name]["segments"]
                for word in segment["words"]
            ]

            for word in my_words:
                context.scene.timeline_markers.new(
                    name=word["text"],
                    frame=context.scene.frame_current + int(framerate * word["start"]),
                )

        wm.progress_end()

        return {"FINISHED"}


class TTS_Audio_Play(bpy.types.Operator):
    bl_label = "Play"
    bl_idname = "tts_client.tts_audio_play"
    bl_description = "Play audio preview"
    bl_options = {"REGISTER", "UNDO"}
    handle = 0

    def execute(self, context):
        # Start progress thread
        threading.Thread(target=progress_func, args=()).start()

        # Get addon preferences and data
        addon_prefs = context.preferences.addons[__package__].preferences
        addon_data = context.scene.tts_client_data

        # Get input text and preview folder path
        _input_text = addon_data.input_text
        _preview_folder = addon_prefs.tts_audio_preview_folder

        # Check for empty input text
        if not _input_text:
            self.report({"ERROR"}, "Input text is empty")
            return {"FINISHED"}

        # Check if project is saved
        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Project is not saved")
            return {"FINISHED"}

        # Generate audio name using MD5 hash
        audio_name = hashlib.md5(_input_text.encode()).hexdigest() + ".wav"

        # Create preview folder if it doesn't exist
        os.makedirs(_preview_folder, exist_ok=True)

        # Get audio file path
        audio_filepath = os.path.join(_preview_folder, audio_name)

        # Generate TTS audio if it doesn't exist
        if not os.path.isfile(audio_filepath):
            transcription_cache[audio_name] = tts_output(audio_filepath)

        # End progress update
        wm.progress_end()

        try:
            # Play audio
            addon_data.audio_is_playing = True
            device = aud.Device()
            audio = aud.Sound.file(audio_filepath)

            TTS_Audio_Play.handle = device.play(audio)
            TTS_Audio_Play.handle.loop_count = -1  # Loop indefinitely

        except Exception as e:
            self.report({"WARNING"}, f"[Play] Error: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}


class TTS_Audio_Pause(bpy.types.Operator):
    bl_label = "Pause"
    bl_idname = "tts_client.tts_audio_pause"
    bl_description = "Pause audio preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        addon_data = context.scene.tts_client_data
        # if (addon_data.audio_loaded):
        addon_data.audio_is_playing = False
        TTS_Audio_Play.handle.stop()
        return {"FINISHED"}


class TTS_PT_Panel(bpy.types.Panel):
    bl_label = "Text To Speach"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "TTS"

    @classmethod
    def poll(self, context):
        return context.space_data.view_type in {"SEQUENCER", "SEQUENCER_PREVIEW"}

    def draw(self, context):
        addon_prefs = bpy.context.preferences.addons[__package__].preferences


class TTS_PT_subpanel_synthesize(bpy.types.Panel):
    bl_parent_id = "TTS_PT_Panel"
    bl_label = "Synthesize"

    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "TTS"

    @classmethod
    def poll(cls, context):
        return True  # Simplified poll method

    def draw(self, context):
        # Get addon preferences and data
        addon_prefs = context.preferences.addons[__package__].preferences
        addon_data = context.scene.tts_client_data

        # Create layout column
        layout = self.layout.column(align=True)

        # Input text field
        layout.prop(addon_data, "input_text", text="", icon="RIGHTARROW")

        # Play/Pause and Add buttons
        row = layout.row(align=True)
        if addon_data.audio_is_playing:
            row.operator("tts_client.tts_audio_pause", text="Pause", icon="PAUSE")
        else:
            row.operator("tts_client.tts_audio_play", text="Play", icon="PLAY_SOUND")
        row.operator("tts_client.tts_audio_add", text="Add", icon="NLA_PUSHDOWN")

        # Transcription markers and Speech speed options
        layout.prop(addon_data, "add_transcription", text="Transcription markers")
        layout.prop(addon_data, "speech_speed", text="Speech speed")


class TTS_PT_subpanel_settings(bpy.types.Panel):
    bl_parent_id = "TTS_PT_Panel"
    bl_label = "Scene Settings"

    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "TTS"

    def draw(self, context):
        # Get addon preferences and data
        addon_data = context.scene.tts_client_data
        # addon_prefs = context.preferences.addons[__package__].preferences  # Unused, so commented out

        layout = self.layout.column(align=True)

        # TTS server settings box
        box = layout.box()
        col = box.column()
        col.label(text="TTS server settings")

        # Model and Speaker ID options
        col.prop(addon_data, "model_name", text="Model")
        col.prop(addon_data, "vctk_vits_speaker_idx", text="Speaker id")


classes = [
    TtsClientAddonPreferences,
    TtsClientData,
    TTS_Audio_Play,
    TTS_Audio_Add,
    TTS_Audio_Pause,
    TTS_PT_Panel,
    TTS_PT_subpanel_synthesize,
    # TTS_PT_subpanel_settings,
]


def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.tts_client_data = bpy.props.PointerProperty(type=TtsClientData)


def unregister():
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)