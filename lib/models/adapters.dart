import 'package:hive/hive.dart';

import 'models.dart';

class StoryAdapter extends TypeAdapter<Story> {
  @override
  final typeId = 0;

  @override
  Story read(BinaryReader reader) {
    final id = reader.readString();
    final title = reader.readString();
    final third = reader.read();

    if (third is bool) {
      final imagePath = third ? reader.readString() : null;
      final videoPath = reader.readBool() ? reader.readString() : null;
      final createdAt = DateTime.parse(reader.readString());
      return Story(
        id: id,
        title: title,
        author: 'DriveCommunity',
        imagePath: imagePath,
        videoPath: videoPath,
        likes: 0,
        views: 0,
        createdAt: createdAt,
        updatedAt: createdAt,
      );
    }

    final author = third as String;
    final authorAvatarUrl = reader.readBool() ? reader.readString() : null;
    final location = reader.readBool() ? reader.readString() : null;
    final description = reader.readBool() ? reader.readString() : null;
    final imagePath = reader.readBool() ? reader.readString() : null;
    final imageUrl = reader.readBool() ? reader.readString() : null;
    final videoPath = reader.readBool() ? reader.readString() : null;
    final videoUrl = reader.readBool() ? reader.readString() : null;
    final likes = reader.readInt();
    final views = reader.readInt();
    final createdAt = DateTime.parse(reader.readString());
    final updatedAt = DateTime.parse(reader.readString());

    return Story(
      id: id,
      title: title,
      author: author,
      authorAvatarUrl: authorAvatarUrl,
      location: location,
      description: description,
      imagePath: imagePath,
      imageUrl: imageUrl,
      videoPath: videoPath,
      videoUrl: videoUrl,
      likes: likes,
      views: views,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }

  @override
  void write(BinaryWriter writer, Story obj) {
    writer.writeString(obj.id);
    writer.writeString(obj.title);
    writer.writeString(obj.author);
    writer.writeBool(obj.authorAvatarUrl != null);
    if (obj.authorAvatarUrl != null) {
      writer.writeString(obj.authorAvatarUrl!);
    }
    writer.writeBool(obj.location != null);
    if (obj.location != null) {
      writer.writeString(obj.location!);
    }
    writer.writeBool(obj.description != null);
    if (obj.description != null) {
      writer.writeString(obj.description!);
    }
    writer.writeBool(obj.imagePath != null);
    if (obj.imagePath != null) {
      writer.writeString(obj.imagePath!);
    }
    writer.writeBool(obj.imageUrl != null);
    if (obj.imageUrl != null) {
      writer.writeString(obj.imageUrl!);
    }
    writer.writeBool(obj.videoPath != null);
    if (obj.videoPath != null) {
      writer.writeString(obj.videoPath!);
    }
    writer.writeBool(obj.videoUrl != null);
    if (obj.videoUrl != null) {
      writer.writeString(obj.videoUrl!);
    }
    writer.writeInt(obj.likes);
    writer.writeInt(obj.views);
    writer.writeString(obj.createdAt.toIso8601String());
    writer.writeString(obj.updatedAt.toIso8601String());
  }
}

class ChatMessageAdapter extends TypeAdapter<ChatMessage> {
  @override
  final typeId = 1;

  @override
  ChatMessage read(BinaryReader reader) {
    final sender = reader.readString();
    final text = reader.readString();
    final timestamp = DateTime.parse(reader.readString());
    final isMe = reader.readBool();

    try {
      final type = chatMessageTypeFromJson(reader.readString());
      final status = messageStatusFromJson(reader.readString());
      final attachmentPath = reader.readBool() ? reader.readString() : null;
      final attachmentUrl = reader.readBool() ? reader.readString() : null;
      final id = reader.readString();
      return ChatMessage(
        id: id,
        sender: sender,
        text: text,
        type: type,
        timestamp: timestamp,
        isMe: isMe,
        status: status,
        attachmentPath: attachmentPath,
        attachmentUrl: attachmentUrl,
      );
    } catch (_) {
      return ChatMessage(
        id: '${sender}_${timestamp.millisecondsSinceEpoch}',
        sender: sender,
        text: text,
        type: ChatMessageType.text,
        timestamp: timestamp,
        isMe: isMe,
        status: MessageStatus.sent,
      );
    }
  }

  @override
  void write(BinaryWriter writer, ChatMessage obj) {
    writer.writeString(obj.sender);
    writer.writeString(obj.text);
    writer.writeString(obj.timestamp.toIso8601String());
    writer.writeBool(obj.isMe);
    writer.writeString(chatMessageTypeToJson(obj.type));
    writer.writeString(messageStatusToJson(obj.status));
    writer.writeBool(obj.attachmentPath != null);
    if (obj.attachmentPath != null) {
      writer.writeString(obj.attachmentPath!);
    }
    writer.writeBool(obj.attachmentUrl != null);
    if (obj.attachmentUrl != null) {
      writer.writeString(obj.attachmentUrl!);
    }
    writer.writeString(obj.id);
  }
}

class ChatThreadAdapter extends TypeAdapter<ChatThread> {
  @override
  final typeId = 2;

  @override
  ChatThread read(BinaryReader reader) {
    final id = reader.readString();
    final title = reader.readString();
    final subtitle = reader.readString();
    final next = reader.read();

    if (next is List && next.isNotEmpty && next.first is ChatMessage) {
      return ChatThread(
        id: id,
        title: title,
        subtitle: subtitle,
        participants: [title],
        unreadCount: 0,
        lastUpdated: DateTime.now(),
        messages: List<ChatMessage>.from(next),
      );
    }

    if (next is List) {
      try {
        final participants = List<String>.from(next.cast<String>());
        final unreadCount = reader.readInt();
        final lastUpdated = DateTime.parse(reader.readString());
        final messages = List<ChatMessage>.from(reader.readList());

        return ChatThread(
          id: id,
          title: title,
          subtitle: subtitle,
          participants: participants,
          unreadCount: unreadCount,
          lastUpdated: lastUpdated,
          messages: messages,
        );
      } catch (_) {
        return ChatThread(
          id: id,
          title: title,
          subtitle: subtitle,
          participants: [title],
          unreadCount: 0,
          lastUpdated: DateTime.now(),
          messages: List<ChatMessage>.from(next),
        );
      }
    }

    return ChatThread(
      id: id,
      title: title,
      subtitle: subtitle,
      participants: [title],
      unreadCount: 0,
      lastUpdated: DateTime.now(),
      messages: const [],
    );
  }

  @override
  void write(BinaryWriter writer, ChatThread obj) {
    writer.writeString(obj.id);
    writer.writeString(obj.title);
    writer.writeString(obj.subtitle);
    writer.writeList(obj.participants);
    writer.writeInt(obj.unreadCount);
    writer.writeString(obj.lastUpdated.toIso8601String());
    writer.writeList(obj.messages);
  }
}
