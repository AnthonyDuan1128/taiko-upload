from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, PasswordField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from models import User


class RegistrationForm(FlaskForm):
    username = StringField('用户名', validators=[
        DataRequired(message='请输入用户名'),
        Length(min=2, max=30, message='用户名长度 2-30 字符')
    ])
    email = StringField('邮箱', validators=[
        DataRequired(message='请输入邮箱'),
        Email(message='邮箱格式不正确')
    ])
    password = PasswordField('密码', validators=[
        DataRequired(message='请输入密码'),
        Length(min=6, max=128, message='密码长度至少 6 位')
    ])
    password2 = PasswordField('确认密码', validators=[
        DataRequired(message='请确认密码'),
        EqualTo('password', message='两次密码不一致')
    ])
    submit = SubmitField('注册')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('该用户名已被注册')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('该邮箱已被注册')


class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[
        DataRequired(message='请输入用户名')
    ])
    password = PasswordField('密码', validators=[
        DataRequired(message='请输入密码')
    ])
    submit = SubmitField('登录')


class UploadForm(FlaskForm):
    title = StringField('曲名', validators=[
        DataRequired(message='请输入曲名'),
        Length(max=200)
    ])
    artist = StringField('作者/艺术家', validators=[
        Length(max=200)
    ])
    song_type = SelectField('分类', choices=[
        ('01 Pop', '流行音乐'),
        ('02 Anime', '动画'),
        ('03 Vocaloid', 'Vocaloid'),
        ('04 Children and Folk', '童谣与民谣'),
        ('05 Variety', '综合'),
        ('06 Classical', '古典'),
        ('07 Game Music', '游戏音乐'),
        ('08 Live Festival Mode', '演奏祭模式'),
        ('09 Namco Original', 'Namco原创'),
    ])
    tja_file = FileField('TJA 谱面文件', validators=[
        FileRequired(message='请上传 TJA 文件'),
        FileAllowed(['tja'], '只允许上传 .tja 文件')
    ])
    ogg_file = FileField('OGG 音频文件', validators=[
        FileRequired(message='请上传 OGG 文件'),
        FileAllowed(['ogg'], '只允许上传 .ogg 文件')
    ])
    submit = SubmitField('提交投稿')


class CommentForm(FlaskForm):
    content = TextAreaField('评论内容', validators=[
        DataRequired(message='请输入评论内容'),
        Length(min=1, max=500, message='评论内容 1-500 字符')
    ])
    submit = SubmitField('发表评论')


class ReviewForm(FlaskForm):
    action = SelectField('审核操作', choices=[
        ('approve', '通过'),
        ('reject', '拒绝'),
    ])
    review_note = TextAreaField('审核备注', validators=[
        Length(max=500)
    ])
    submit = SubmitField('提交审核')
