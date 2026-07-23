enum ChatMessageType { text, image, video }

enum MessageStatus { sent, delivered, read }

String chatMessageTypeToJson(ChatMessageType type) => type.name;

ChatMessageType chatMessageTypeFromJson(String value) {
  return ChatMessageType.values.firstWhere(
    (type) => type.name == value,
    orElse: () => ChatMessageType.text,
  );
}

String messageStatusToJson(MessageStatus status) => status.name;

MessageStatus messageStatusFromJson(String value) {
  return MessageStatus.values.firstWhere(
    (status) => status.name == value,
    orElse: () => MessageStatus.sent,
  );
}

class Story {
  final String id;
  final String title;
  final String author;
  final String? authorAvatarUrl;
  final String? location;
  final String? description;
  final String? imagePath;
  final String? imageUrl;
  final String? videoPath;
  final String? videoUrl;
  final int likes;
  final int views;
  final DateTime createdAt;
  final DateTime updatedAt;

  Story({
    required this.id,
    required this.title,
    required this.author,
    this.authorAvatarUrl,
    this.location,
    this.description,
    this.imagePath,
    this.imageUrl,
    this.videoPath,
    this.videoUrl,
    required this.likes,
    required this.views,
    required this.createdAt,
    required this.updatedAt,
  });

  bool get isVideo => videoPath != null || videoUrl != null;
  bool get hasLocalMedia => imagePath != null || videoPath != null;
  bool get hasRemoteMedia => imageUrl != null || videoUrl != null;

  factory Story.fromJson(Map<String, dynamic> json) => Story(
        id: json['id'] as String,
        title: json['title'] as String,
        author: json['author'] as String? ?? 'DriveCommunity',
        authorAvatarUrl: json['authorAvatarUrl'] as String?,
        location: json['location'] as String?,
        description: json['description'] as String?,
        imagePath: json['imagePath'] as String?,
        imageUrl: json['imageUrl'] as String?,
        videoPath: json['videoPath'] as String?,
        videoUrl: json['videoUrl'] as String?,
        likes: json['likes'] as int? ?? 0,
        views: json['views'] as int? ?? 0,
        createdAt: DateTime.parse(json['createdAt'] as String),
        updatedAt: DateTime.parse(json['updatedAt'] as String? ?? json['createdAt'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'author': author,
        'authorAvatarUrl': authorAvatarUrl,
        'location': location,
        'description': description,
        'imagePath': imagePath,
        'imageUrl': imageUrl,
        'videoPath': videoPath,
        'videoUrl': videoUrl,
        'likes': likes,
        'views': views,
        'createdAt': createdAt.toIso8601String(),
        'updatedAt': updatedAt.toIso8601String(),
      };
}

class ChatMessage {
  final String id;
  final String sender;
  final String text;
  final ChatMessageType type;
  final DateTime timestamp;
  final bool isMe;
  final MessageStatus status;
  final String? attachmentPath;
  final String? attachmentUrl;

  ChatMessage({
    required this.id,
    required this.sender,
    required this.text,
    required this.type,
    required this.timestamp,
    required this.isMe,
    required this.status,
    this.attachmentPath,
    this.attachmentUrl,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        id: json['id'] as String,
        sender: json['sender'] as String,
        text: json['text'] as String,
        type: chatMessageTypeFromJson(json['type'] as String? ?? 'text'),
        timestamp: DateTime.parse(json['timestamp'] as String),
        isMe: json['isMe'] as bool,
        status: messageStatusFromJson(json['status'] as String? ?? 'sent'),
        attachmentPath: json['attachmentPath'] as String?,
        attachmentUrl: json['attachmentUrl'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'sender': sender,
        'text': text,
        'type': chatMessageTypeToJson(type),
        'timestamp': timestamp.toIso8601String(),
        'isMe': isMe,
        'status': messageStatusToJson(status),
        'attachmentPath': attachmentPath,
        'attachmentUrl': attachmentUrl,
      };
}

class ChatThread {
  final String id;
  final String title;
  final String subtitle;
  final List<String> participants;
  final int unreadCount;
  final DateTime lastUpdated;
  final List<ChatMessage> messages;

  ChatThread({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.participants,
    required this.unreadCount,
    required this.lastUpdated,
    required this.messages,
  });

  factory ChatThread.fromJson(Map<String, dynamic> json) => ChatThread(
        id: json['id'] as String,
        title: json['title'] as String,
        subtitle: json['subtitle'] as String,
        participants: (json['participants'] as List<dynamic>?)
                ?.map((participant) => participant as String)
                .toList() ??
            [json['title'] as String],
        unreadCount: json['unreadCount'] as int? ?? 0,
        lastUpdated: DateTime.parse(json['lastUpdated'] as String? ?? DateTime.now().toIso8601String()),
        messages: (json['messages'] as List<dynamic>)
            .map((message) => ChatMessage.fromJson(message as Map<String, dynamic>))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'subtitle': subtitle,
        'participants': participants,
        'unreadCount': unreadCount,
        'lastUpdated': lastUpdated.toIso8601String(),
        'messages': messages.map((message) => message.toJson()).toList(),
      };
}
